"""Development V4: fixed relative/context ensemble with causal missing history.

No current missing measurement is scored. Only past history is forward-filled
for at most two rows, with original observation fractions supplied as features.
Scores are binary EVENT rankings, never water-safety or valve permissions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits

CHANNELS18 = ["Tp", "Cl", "pH", "Redox", "Leit", "Trueb", "Cl_2", "Fm", "Fm_2"]
CHANNELS19 = ["Tp", "pH", "Cond", "Turb", "SAC", "PFM"]
CONFIG = {
    "seed": 20261016, "history_windows": [15, 60], "history_fill_limit": 2,
    "minimum_original_observation_fractions": [.5, .5],
    "ensemble_weights": {"relative": .75, "context": .25},
    "relative_model": {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 10,
                       "max_features": .7, "n_jobs": 2},
    "context_model": {"max_iter": 100, "max_leaf_nodes": 7, "min_samples_leaf": 80,
                      "learning_rate": .05, "l2_regularization": 10., "early_stopping": False},
    "sample_weights": "equal total positive weight per original event; balanced total positive/negative weight; four equal-time negative blocks",
}


def intervals(mask):
    changes = np.diff(np.r_[False, np.asarray(mask,dtype=bool), False].astype(np.int8))
    return list(zip(np.flatnonzero(changes==1), np.flatnonzero(changes==-1)))


def training_weights(labels, eligible):
    """Each original labeled event has equal total weight, no label expansion."""
    y=np.asarray(labels,dtype=bool)
    weights=np.zeros(len(y),dtype=float)
    event_groups=[]
    for start,end in intervals(y):
        indices=np.flatnonzero(eligible[start:end])+start
        if indices.size:event_groups.append(indices)
    negative_groups=[]
    for indices in np.array_split(np.arange(len(y)),4):
        keep=indices[eligible[indices] & ~y[indices]]
        if keep.size:negative_groups.append(keep)
    if not event_groups or not negative_groups:
        raise ValueError("Both eligible original classes are required")
    for group in event_groups:weights[group]=.5/(len(event_groups)*len(group))
    for group in negative_groups:weights[group]=.5/(len(negative_groups)*len(group))
    weights*=eligible.sum()
    return weights[eligible]


class FixedRelativeContextDetector:
    def __init__(self, channels=None, recipe="ensemble"):
        self.channels=list(channels or CHANNELS18)
        if recipe not in ("relative", "ensemble"):
            raise ValueError("recipe must be relative or ensemble")
        self.recipe=recipe
        self.max_lookback=62

    def _frame(self,frame):
        return frame[self.channels].astype(float).replace([np.inf,-np.inf],np.nan).reset_index(drop=True)

    def fit(self,frame,labels):
        x=self._frame(frame)
        y=np.asarray(labels)
        if y.ndim!=1 or len(y)!=len(x) or not np.isin(y,[0,1]).all():
            raise ValueError("labels must be binary and match the training frame")
        y=y.astype(bool)
        self.fit_rows_=0
        self.fit_event_count_=0
        self.fit_status_="unfitted"
        normal=x.notna().all(axis=1).to_numpy() & ~y
        normal_pairs=normal & np.r_[False,normal[:-1]]
        if normal.sum()<100:
            self.fit_status_="insufficient_normal_training"
            return self
        self.center_=x.loc[normal].median().to_numpy()
        span=(x.loc[normal].quantile(.75)-x.loc[normal].quantile(.25)).to_numpy()
        steps=x.diff().abs().loc[normal_pairs]
        floors=[]
        for j,c in enumerate(self.channels):
            positive=steps[c].to_numpy();positive=positive[np.isfinite(positive)&(positive>0)]
            quantum=float(np.quantile(positive,.75)) if len(positive) else 0.
            floors.append(max(quantum,span[j]*.005,abs(self.center_[j])*1e-9,1e-9))
        self.floor_=np.asarray(floors)
        self.level_scale_=np.maximum(span,self.floor_*10)
        relative,context,eligible=self.features(frame)
        self.fit_rows_=int(eligible.sum())
        self.fit_event_count_=int(sum(np.any(eligible[s:e]) for s,e in intervals(y)))
        if len(np.unique(y[eligible]))<2:
            self.fit_status_="one_class_training"
            return self
        weights=training_weights(y,eligible)
        self.relative_=ExtraTreesClassifier(**CONFIG["relative_model"],random_state=CONFIG["seed"])
        self.context_=HistGradientBoostingClassifier(**CONFIG["context_model"],random_state=CONFIG["seed"])
        with threadpool_limits(limits=1):
            self.relative_.fit(relative[eligible],y[eligible].astype(int),sample_weight=weights)
            self.context_.fit(context[eligible],y[eligible].astype(int),sample_weight=weights)
        self.fit_status_="fitted"
        return self

    def features(self,frame):
        if not hasattr(self,"floor_"):raise RuntimeError("Fit normal scales first")
        x=self._frame(frame)
        past=x.ffill(limit=CONFIG["history_fill_limit"]).shift(1)
        original_past=x.shift(1)
        complete=x.notna().all(axis=1).to_numpy()
        parts=[np.clip((x-past).to_numpy()/self.floor_,-50,50)]
        eligible=complete.copy()
        med60=None
        for window in CONFIG["history_windows"]:
            minimum=int(np.ceil(window*.5))
            rolling=past.rolling(window,min_periods=minimum)
            center=rolling.median()
            spread=(rolling.quantile(.75)-rolling.quantile(.25))/1.349
            scale=np.maximum(spread.to_numpy(),self.floor_)
            fraction=original_past.notna().rolling(window,min_periods=1).sum()/window
            # original (not filled) observation density must be adequate in every channel.
            eligible &= (fraction.to_numpy()>=.5).all(axis=1)
            parts += [np.clip((x-center).to_numpy()/scale,-50,50),
                      np.clip((past.rolling(5,min_periods=3).mean()-center).to_numpy()/scale,-50,50),
                      np.log1p(np.clip(spread.to_numpy()/self.floor_,0,1e4)),
                      fraction.to_numpy()]
            if window==60:med60=center.to_numpy()
        relative=np.concatenate(parts,axis=1)
        context=np.concatenate([relative,np.clip((x.to_numpy()-self.center_)/self.level_scale_,-20,20),
                                np.clip((med60-self.center_)/self.level_scale_,-20,20)],axis=1)
        eligible &= np.isfinite(relative).all(axis=1) & np.isfinite(context).all(axis=1)
        return relative,context,eligible

    def score_components(self,frame):
        outputs={key:np.full(len(frame),np.nan) for key in ("relative","context","ensemble")}
        if getattr(self,"fit_status_","unfitted")!="fitted":return outputs
        relative,context,eligible=self.features(frame)
        if eligible.any():
            with threadpool_limits(limits=1):
                outputs["relative"][eligible]=self.relative_.predict_proba(relative[eligible])[:,1]
                outputs["context"][eligible]=self.context_.predict_proba(context[eligible])[:,1]
            outputs["ensemble"][eligible]=.75*outputs["relative"][eligible]+.25*outputs["context"][eligible]
        return outputs

    def score(self,frame):
        return self.score_components(frame)[self.recipe]

    def score_reasons(self,frame):
        """Mutually exclusive reasons; structural warmup is separate from missing history."""
        status=getattr(self,"fit_status_","unfitted")
        if status!="fitted":return np.full(len(frame),status,dtype=object)
        x=self._frame(frame)
        _,_,eligible=self.features(frame)
        reason=np.full(len(frame),"available",dtype=object)
        reason[~eligible]="history_missing"
        reason[np.arange(len(frame))<30]="warmup"
        reason[~x.notna().all(axis=1).to_numpy()]="current_missing"
        return reason


class InvariantRelativeDetector(FixedRelativeContextDetector):
    """Attempt 2: channel-anonymous absolute relative shapes, fixed ET family.

    This disclosed development variant removes channel identity and deviation
    sign from the relative detector; it is not selected from independent data.
    """
    def __init__(self,channels=None):
        super().__init__(channels,recipe="relative")

    def pooled_features(self,relative):
        grouped=relative.reshape(len(relative),9,len(self.channels))
        parts=[]
        for j in (0,1,2,3,5,6,7):
            values=np.abs(grouped[:,j,:])
            ordered=np.sort(values,axis=1)
            parts.extend([ordered[:,-1],ordered[:,-min(2,len(self.channels)):].mean(axis=1),
                          np.median(values,axis=1),values.mean(axis=1)])
        for j in (4,8):
            parts.extend([grouped[:,j,:].min(axis=1),grouped[:,j,:].mean(axis=1)])
        return np.column_stack(parts)

    def fit(self,frame,labels):
        super().fit(frame,labels)
        if self.fit_status_!="fitted":return self
        relative,_,eligible=self.features(frame)
        self.invariant_=ExtraTreesClassifier(**CONFIG["relative_model"],random_state=CONFIG["seed"])
        with threadpool_limits(limits=1):
            self.invariant_.fit(self.pooled_features(relative)[eligible],np.asarray(labels,dtype=int)[eligible],
                                sample_weight=training_weights(labels,eligible))
        return self

    def score_components(self,frame):
        scores=np.full(len(frame),np.nan)
        if getattr(self,"fit_status_","unfitted")!="fitted":return {"invariant":scores}
        relative,_,eligible=self.features(frame)
        if eligible.any():
            with threadpool_limits(limits=1):
                scores[eligible]=self.invariant_.predict_proba(self.pooled_features(relative)[eligible])[:,1]
        return {"invariant":scores}

    def score(self,frame):return self.score_components(frame)["invariant"]


def self_test():
    rng=np.random.default_rng(4)
    frame=pd.DataFrame(rng.normal(size=(500,3)),columns=["a","b","c"])
    labels=np.zeros(500,dtype=int);labels[100:115]=1;labels[300:330]=1
    detector=FixedRelativeContextDetector(["a","b","c"]).fit(frame,labels)
    before=detector.score(frame)
    altered=frame.copy();altered.iloc[350:]=99999
    np.testing.assert_allclose(before[:350],detector.score(altered)[:350],equal_nan=True)
    np.testing.assert_allclose(before[:350],detector.score(frame.iloc[:350]),equal_nan=True)
    missing=frame.copy();missing.iloc[200]=np.nan
    scores=detector.score(missing)
    assert np.isnan(scores[200]) and np.isfinite(scores[201])
    weights=training_weights(labels,np.ones(500,dtype=bool))
    assert np.isclose(weights[100:115].sum(),weights[300:330].sum())
    assert np.isclose(weights[labels==1].sum(),weights[labels==0].sum())
    single=FixedRelativeContextDetector(["a","b","c"]).fit(frame,np.zeros(len(frame)))
    assert single.fit_status_=="one_class_training" and np.isnan(single.score(frame)).all()
    print("PASS: causal prefix/future mutation, missing current unavailable/history recovery, event-balanced weights")


if __name__=="__main__":self_test()
