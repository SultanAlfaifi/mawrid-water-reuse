"""Known-normal support is required before the classifier may suppress IF.

An out-of-support shape is unknown, not normal. The calibration layer retains
the original baseline wherever shape is NaN. Quantiles tune a geometric normal
reference, not a probability of water safety or an accuracy guarantee.
"""
from __future__ import annotations
import numpy as np
from recovery_candidate import RecoveryEventDetector
from normal_support import NormalSupportGate,SupportConfig

CONFIGS={'support_q50':{'reference_quantile':.50},'support_q95':{'reference_quantile':.95}}


class SupportedRecoveryDetector(RecoveryEventDetector):
    def __init__(self,config_id='support_q50',channels=None):
        if config_id not in CONFIGS:raise ValueError(f'Unknown supported recipe: {config_id}')
        # Parent feature extraction must remain the invariant recipe.
        super().__init__('shape_invariant',channels)
        self.support_config_id=config_id

    def fit(self,frame,labels):
        super().fit(frame,labels)
        self.support_=NormalSupportGate(SupportConfig(**CONFIGS[self.support_config_id]))
        if not hasattr(self,'noise_floor_'):
            self.support_fit_skipped_='no_supported_feature_scaler'
            return self
        X,eligible=self.features(frame)
        self.support_.fit(X,~np.asarray(labels,dtype=bool),eligible)
        self.support_fit_skipped_=None
        return self

    def score_components(self,frame):
        result=super().score_components(frame)
        result['shape_raw']=result['shape'].copy()
        result['support_distance']=np.full(len(frame),np.nan)
        if self.shape_ is None or self.support_fit_skipped_ is not None:
            result['shape'][:]=np.nan
            return result
        X,eligible=self.features(frame)
        distance=self.support_.distance(X)
        supported=(np.isfinite(distance)&(distance<=self.support_.threshold_)&eligible
                   if self.support_.fit_status_=='fitted' else np.zeros(len(frame),dtype=bool))
        result['support_distance'][eligible]=distance[eligible]
        result['shape'][~supported]=np.nan
        return result
