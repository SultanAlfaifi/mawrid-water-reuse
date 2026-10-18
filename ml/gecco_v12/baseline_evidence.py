"""V12 adds only frozen original-IF score and observed bit to V9 features.

The IF is never fitted here. No parent wrapper, threshold, policy or label is
used in these sensor-derived features. Original references, HGB training
weights/parameters and prediction availability are inherited unchanged.
"""
from __future__ import annotations
from copy import copy
import hashlib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.utils.validation import check_is_fitted
from ml.gecco_v2.candidates_supervised import build_features
from ml.gecco_v9.conditional import ConditionalResidualHGBScorer

BASELINE_ADDED_NAMES=('original_if_raw_anomaly_score','original_if_score_observed')


def baseline_state_digest(value):
    """SHA256 of typed, length-delimited fitted state, excluding record padding.

    The semantic encoding follows the established frozen lineage audit's
    approach, implemented locally so inference never imports audit code.
    sklearn tree records contain undefined alignment bytes that can change
    during serialization. Every named field and estimator attribute remains
    included; only those undefined padding bytes are excluded.
    """
    digest=hashlib.sha256()
    def write(payload):
        digest.update(len(payload).to_bytes(8,'big'));digest.update(payload)
    def add(item):
        if isinstance(item,np.generic):add(item.item());return
        if item is None or isinstance(item,(str,bool,int,float)):
            write((type(item).__name__+':'+repr(item)).encode());return
        if isinstance(item,bytes):write(b'bytes:');write(item);return
        if isinstance(item,np.ndarray):
            write(('array:'+str(item.shape)+':'+str(item.dtype)).encode())
            if item.dtype.names:
                for name in item.dtype.names:add(name);add(item[name])
            elif item.dtype.hasobject:
                for part in item.flat:add(part)
            else:write(np.ascontiguousarray(item).tobytes())
            return
        if isinstance(item,dict):
            write(('dict:'+str(len(item))).encode())
            for key in sorted(item,key=lambda key:(type(key).__name__,repr(key))):add(key);add(item[key])
            return
        if isinstance(item,(tuple,list)):
            write((type(item).__name__+':'+str(len(item))).encode())
            for part in item:add(part)
            return
        if isinstance(item,type):add('class:'+item.__module__+'.'+item.__qualname__);return
        if isinstance(item,np.random.Generator):add('numpy_generator');add(item.bit_generator.state);return
        if isinstance(item,np.random.RandomState):add('numpy_random_state');add(item.get_state());return
        add('object:'+type(item).__module__+'.'+type(item).__qualname__)
        if hasattr(item,'__dict__'):add(vars(item))
        elif hasattr(item,'__getstate__'):
            state=item.__getstate__()
            if state is None:raise TypeError('Unsupported stateless IF object: '+str(type(item)))
            add(state)
        else:raise TypeError('Unsupported fitted IF state: '+str(type(item)))
    add(value)
    return digest.hexdigest()


class BaselineEvidenceHGBScorer(ConditionalResidualHGBScorer):
    """V9 prefix plus two float32 columns; unavailable added evidence is [0,0]."""
    def __init__(self,channels,baseline_estimator):
        super().__init__(channels)
        empty=pd.DataFrame({c:pd.Series(dtype=float) for c in self.channels})
        _,_,names=build_features(empty,'baseline15',self.channels)
        self.expected_baseline_feature_names_=list(names)
        if len(names)!=4*len(self.channels):raise ValueError('Frozen baseline15 schema changed')
        if baseline_estimator is not None:
            if not isinstance(baseline_estimator,IsolationForest):raise ValueError('Only a fitted original IsolationForest or None is supported')
            check_is_fitted(baseline_estimator,['estimators_','n_features_in_'])
            if baseline_estimator.n_features_in_!=len(names):raise ValueError('Frozen IF feature count mismatch')
            if hasattr(baseline_estimator,'feature_names_in_') and list(baseline_estimator.feature_names_in_)!=names:
                raise ValueError('Frozen IF named feature order mismatch')
        self.baseline_estimator_=baseline_estimator
        self.baseline_state_hash_at_attachment_=baseline_state_digest(baseline_estimator)
        self.v9_feature_names_=list(self.feature_names_)
        self.baseline_feature_names_=list(BASELINE_ADDED_NAMES)
        self.feature_names_=self.v9_feature_names_+self.baseline_feature_names_
        self.feature_contract_['version']='long_context_hgb_onset_conditional_frozen_if_v1'
        self.feature_contract_['feature_count']=len(self.feature_names_)
        self.feature_contract_['feature_names']=list(self.feature_names_)
        self.feature_contract_['original_if_evidence']={
            'added_features':list(BASELINE_ADDED_NAMES),'added_count':2,
            'source':'Only the already fitted original training IsolationForest; no parent detector, threshold or policy.',
            'input_feature_set':'baseline15','input_feature_names':list(names),'channel_order':list(self.channels),
            'input_schema':'Four original ordered feature groups: values, absolute first difference, residual from current-inclusive rolling15 mean, rolling15 std(ddof=0). Full finite15-row lookback required.',
            'channel_alignment':'Caller supplies original training channel order. Width and any estimator feature_names_in_ are checked; a NumPy-fitted estimator alone cannot identify sensor names.',
            'raw_score':'Negative frozen IF.score_samples on eligible rows, float64. No threshold, calibration, clipping or refit.',
            'matrix_representation':'Raw finite score cast to float32 plus observed bit1; missing or nonfinite/unrepresentable score gives [0,0].',
            'missing_estimator':'None gives [0,0] without changing V9 availability.',
            'training_scope':'Original IF was fitted on known-normal training windows. HGB scores the same training rows in-sample, not cross-fitted or out-of-fold. This is a representation, not independent evidence or calibrated probability.',
            'no_if_fit':True,'original_availability':'V9 availability, weights and fit population unchanged.',
            'maximum_lookback_samples':self.max_lookback_samples,
            'numeric_context_limitation':'Frozen pandas baseline15 rolling calculations are prefix-causal, but cropping15/1441 rows can change numerical state and IF tree paths. This addition does not fix or validate streaming score parity.',
        }

    def baseline_raw_scores(self,frame):
        """Float64 score on original row axis, NaN unavailable; never refits."""
        x=self._frame(frame);scores=np.full(len(x),np.nan,dtype=np.float64)
        if self.baseline_estimator_ is None or not len(x):return scores
        matrix,eligible,names=build_features(x,'baseline15',self.channels)
        if names!=self.expected_baseline_feature_names_:raise ValueError('Frozen baseline15 feature order changed')
        if eligible.any():
            values=-np.asarray(self.baseline_estimator_.score_samples(matrix[eligible]),dtype=np.float64)
            if values.shape!=(int(eligible.sum()),):raise ValueError('Frozen IF returned invalid score shape')
            scores[eligible]=values
        return scores

    def baseline_features(self,frame):
        scores=self.baseline_raw_scores(frame);added=np.zeros((len(scores),2),np.float32)
        with np.errstate(over='ignore',invalid='ignore'):represented=scores.astype(np.float32)
        observed=np.isfinite(scores)&np.isfinite(represented)
        added[observed,0]=represented[observed];added[observed,1]=1
        return added

    def baseline_observed(self,frame):
        return self.baseline_features(frame)[:,1]==1

    def features(self,frame):
        # V9 restores its own V8 width before appending conditional3*C. Keep
        # original_feature_names_ meaning V8 and append IF only after full V9.
        v9_view=copy(self);v9_view.feature_names_=self.v9_feature_names_
        matrix,available=ConditionalResidualHGBScorer.features(v9_view,frame)
        return np.concatenate((matrix,self.baseline_features(frame)),axis=1),available

    def inspection(self):
        result=super().inspection();estimator=self.baseline_estimator_
        current_hash=baseline_state_digest(estimator)
        result['original_if_evidence']={
            'estimator_available':estimator is not None,
            'estimator_type':type(estimator).__name__ if estimator is not None else None,
            'estimator_parameters':estimator.get_params(deep=False) if estimator is not None else None,
            'estimator_n_features_in':int(estimator.n_features_in_) if estimator is not None else None,
            'state_hash_algorithm':'SHA256 length-delimited semantic fitted state; named structured fields exclude undefined padding','state_hash_at_attachment':self.baseline_state_hash_at_attachment_,
            'state_hash_current':current_hash,'state_unchanged':current_hash==self.baseline_state_hash_at_attachment_,
            'feature_names':list(self.baseline_feature_names_),'input_feature_names':list(self.expected_baseline_feature_names_),
            'channel_order':list(self.channels),'in_sample_training_representation':True,'cross_fitted':False,'if_fitted_here':False,
        }
        return result
