"""Synthetic-only V12 feature, fitting, immutability and causal tests."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.exceptions import NotFittedError
from threadpoolctl import threadpool_limits
from ml.gecco_v2.candidates_supervised import build_features
from ml.gecco_v7.long_context_hgb import HGB_PARAMS
from ml.gecco_v8.onset import OnsetWeightedHGBScorer
from ml.gecco_v8.test_onset import weighting_fixture
from ml.gecco_v9.conditional import ConditionalResidualHGBScorer,REFERENCE_ATTRIBUTES
from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer,BASELINE_ADDED_NAMES,baseline_state_digest


def fitted_if(frame,labels):
    matrix,eligible,_=build_features(frame,'baseline15',list(frame.columns))
    known_normal=pd.Series(labels==0).rolling(15,min_periods=15).sum().eq(15).to_numpy()
    return IsolationForest(n_estimators=13,max_samples=128,random_state=91,n_jobs=1).fit(matrix[eligible&known_normal])


class BaselineEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame,cls.labels=weighting_fixture();cls.channels=list(cls.frame.columns)
        cls.estimator=fitted_if(cls.frame,cls.labels);cls.before=joblib.hash(cls.estimator,hash_name='sha1')
        with threadpool_limits(limits=1),patch.object(IsolationForest,'fit',side_effect=AssertionError('IF must never refit')):
            cls.scorer=BaselineEvidenceHGBScorer(cls.channels,cls.estimator).fit(cls.frame,cls.labels)
            cls.original=ConditionalResidualHGBScorer(cls.channels).fit(cls.frame,cls.labels)

    def test_exact_v9_feature_prefix_and_two_columns_no_double_append(self):
        original,oa=self.original.features(self.frame);current,ca=self.scorer.features(self.frame)
        self.assertEqual(current.dtype,np.float32);self.assertEqual(current.shape,(len(self.frame),original.shape[1]+2))
        np.testing.assert_array_equal(current[:,:-2],original);np.testing.assert_array_equal(oa,ca)
        np.testing.assert_array_equal(current[:,-2:],self.scorer.baseline_features(self.frame))
        self.assertEqual(self.scorer.v9_feature_names_,self.original.feature_names_)
        self.assertEqual(self.scorer.original_feature_names_,self.original.original_feature_names_)
        self.assertEqual(self.scorer.conditional_feature_names_,self.original.conditional_feature_names_)
        self.assertEqual(self.scorer.feature_names_,self.original.feature_names_+list(BASELINE_ADDED_NAMES))
        self.assertEqual(self.scorer.max_lookback_samples,1440)

    def test_raw_scores_match_original_if_complete_feature_protocol(self):
        matrix,eligible,names=build_features(self.frame,'baseline15',self.channels)
        expected=np.full(len(self.frame),np.nan);expected[eligible]=-self.estimator.score_samples(matrix[eligible])
        actual=self.scorer.baseline_raw_scores(self.frame)
        self.assertEqual(actual.dtype,np.float64);np.testing.assert_array_equal(actual,expected)
        observed=np.isfinite(expected);features=self.scorer.baseline_features(self.frame)
        np.testing.assert_array_equal(features[:,1],observed.astype(np.float32))
        np.testing.assert_array_equal(features[observed,0],expected[observed].astype(np.float32))
        self.assertTrue((features[~observed]==0).all())
        self.assertEqual(names,self.scorer.expected_baseline_feature_names_)

    def test_weights_references_ridge_fit_population_and_hgb_parameters_unchanged(self):
        self.assertIs(BaselineEvidenceHGBScorer.fit,OnsetWeightedHGBScorer.fit)
        self.assertIs(BaselineEvidenceHGBScorer.score_components,ConditionalResidualHGBScorer.score_components)
        for attr in REFERENCE_ATTRIBUTES+('training_eligible_mask_','training_normalized_weight_','training_sample_weight_',
            'conditional_fit_mask_','conditional_complete_normal_mask_','conditional_coef_','conditional_intercept_','conditional_residual_scale_'):
            np.testing.assert_array_equal(getattr(self.scorer,attr),getattr(self.original,attr))
        self.assertEqual(self.scorer.onset_weight_audit_,self.original.onset_weight_audit_)
        self.assertEqual(self.scorer.fit_status_,self.original.fit_status_)
        for key,value in HGB_PARAMS.items():self.assertEqual(self.scorer.model_.get_params()[key],value)
        self.assertEqual(self.scorer.model_.n_features_in_,self.original.model_.n_features_in_+2)
        self.assertTrue((self.scorer.training_normalized_weight_[self.labels==-1]==0).all())

    def test_if_state_identical_after_full_hgb_training_and_repeated_inference(self):
        self.assertEqual(joblib.hash(self.estimator,hash_name='sha1'),self.before)
        self.assertIs(self.scorer.baseline_estimator_,self.estimator)
        with patch.object(IsolationForest,'fit',side_effect=AssertionError('IF must not fit')):
            for _ in range(2):self.scorer.score_components(self.frame);self.scorer.baseline_features(self.frame)
        self.assertEqual(joblib.hash(self.estimator,hash_name='sha1'),self.before)
        self.assertEqual(self.scorer.baseline_state_hash_at_attachment_,baseline_state_digest(self.estimator))
        self.assertTrue(self.scorer.inspection()['original_if_evidence']['state_unchanged'])
        self.assertFalse(any(k in self.scorer.__dict__ for k in ('parent_bundle','reference_bundle','baseline_threshold','selected')))

    def test_no_labels_or_other_columns_read_by_inference(self):
        extra=self.frame.copy();extra['label']=np.arange(len(extra));extra['EVENT']='do not parse';extra['baseline_prediction']=1
        expected=self.scorer.baseline_raw_scores(self.frame)
        np.testing.assert_array_equal(self.scorer.baseline_raw_scores(extra),expected)
        np.testing.assert_array_equal(self.scorer.features(extra)[0],self.scorer.features(self.frame)[0])
        first=self.scorer.score_components(self.frame);second=self.scorer.score_components(extra)
        for key in first:np.testing.assert_array_equal(first[key],second[key])

    def test_missing_and_infinite_sensor_history_mask_without_availability_change(self):
        frame=self.frame.iloc[:250].copy();frame.iloc[100,0]=np.nan;frame.iloc[120,1]=np.inf;frame.iloc[140,2]=-np.inf
        features=self.scorer.baseline_features(frame);matrix,eligible,_=build_features(frame,'baseline15',self.channels)
        np.testing.assert_array_equal(features[:,1],eligible.astype(np.float32))
        self.assertTrue((features[100:115]==0).all());self.assertTrue((features[120:135]==0).all());self.assertTrue((features[140:155]==0).all())
        np.testing.assert_array_equal(self.scorer.features(frame)[1],self.original.features(frame)[1])
        self.assertTrue(self.scorer.features(frame)[1][100])
        self.assertTrue(np.isfinite(features).all())

    def test_none_estimator_adds_zeros_and_preserves_original_availability(self):
        with threadpool_limits(limits=1):scorer=BaselineEvidenceHGBScorer(self.channels,None).fit(self.frame,self.labels)
        self.assertTrue(np.isnan(scorer.baseline_raw_scores(self.frame)).all())
        self.assertTrue((scorer.baseline_features(self.frame)==0).all());self.assertFalse(scorer.baseline_observed(self.frame).any())
        np.testing.assert_array_equal(scorer.features(self.frame)[0][:,:-2],self.original.features(self.frame)[0])
        np.testing.assert_array_equal(scorer.features(self.frame)[1],self.original.features(self.frame)[1])
        np.testing.assert_array_equal(scorer.training_sample_weight_,self.original.training_sample_weight_)
        json.dumps(scorer.inspection(),allow_nan=False)

    def test_nonfinite_returned_scores_and_float32_overflow_are_unobserved(self):
        def values(matrix):
            scores=np.full(len(matrix),-.4);scores[:4]=[np.nan,np.inf,-np.inf,-1e300];return scores
        with patch.object(self.estimator,'score_samples',side_effect=values):
            raw=self.scorer.baseline_raw_scores(self.frame);added=self.scorer.baseline_features(self.frame)
        self.assertTrue(np.isfinite(added).all());observed=np.flatnonzero(np.isfinite(raw))
        self.assertTrue((added[np.flatnonzero(~np.isfinite(raw))]==0).all())
        self.assertEqual(added[observed[0],1],0);self.assertTrue((added[observed[1:],1]==1).all())

    def test_full_prefix_and_future_mutation_causality(self):
        expected=self.scorer.baseline_raw_scores(self.frame);matrix,available=self.scorer.features(self.frame);scores=self.scorer.score_components(self.frame)
        for stop in (0,1,14,15,61,132,450,len(self.frame)-1):
            part=self.frame.iloc[:stop]
            np.testing.assert_array_equal(self.scorer.baseline_raw_scores(part),expected[:stop])
            current,mask=self.scorer.features(part);np.testing.assert_array_equal(current,matrix[:stop]);np.testing.assert_array_equal(mask,available[:stop])
            for key,value in self.scorer.score_components(part).items():np.testing.assert_array_equal(value,scores[key][:stop])
        changed=self.frame.copy();changed.iloc[200:]=1e4
        np.testing.assert_array_equal(self.scorer.baseline_raw_scores(changed)[:200],expected[:200])
        np.testing.assert_array_equal(self.scorer.features(changed)[0][:200],matrix[:200])

    def test_unknown_and_positive_measurements_never_refit_normal_ridge_or_if(self):
        frame=self.frame.copy();frame.loc[self.labels!=0,:]=np.arange(len(self.channels))+1e4
        with threadpool_limits(limits=1),patch.object(IsolationForest,'fit',side_effect=AssertionError('No IF refit')):
            scorer=BaselineEvidenceHGBScorer(self.channels,self.estimator).fit(frame,self.labels)
        for attr in REFERENCE_ATTRIBUTES+('conditional_fit_mask_','conditional_coef_','conditional_intercept_','conditional_residual_scale_'):
            np.testing.assert_array_equal(getattr(scorer,attr),getattr(self.scorer,attr))
        self.assertEqual(joblib.hash(self.estimator,hash_name='sha1'),self.before)

    def test_repeat_fit_determinism_and_serialization(self):
        with threadpool_limits(limits=1):again=BaselineEvidenceHGBScorer(self.channels,self.estimator).fit(self.frame,self.labels)
        for key,value in self.scorer.score_components(self.frame).items():np.testing.assert_array_equal(value,again.score_components(self.frame)[key])
        copied=deepcopy(self.scorer);np.testing.assert_array_equal(copied.features(self.frame)[0],self.scorer.features(self.frame)[0])
        json.dumps(copied.inspection(),allow_nan=False)

    def test_attachment_hash_survives_joblib_roundtrip_and_detects_state_mutation(self):
        before=self.scorer.inspection()['original_if_evidence']
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'scorer.joblib';joblib.dump(self.scorer,path,compress=3);restored=joblib.load(path)
        self.assertEqual(restored.inspection()['original_if_evidence'],before)
        self.assertEqual(restored.baseline_state_hash_at_attachment_,baseline_state_digest(restored.baseline_estimator_))
        np.testing.assert_array_equal(restored.baseline_raw_scores(self.frame),self.scorer.baseline_raw_scores(self.frame))
        restored.baseline_estimator_.offset_-=.1
        self.assertFalse(restored.inspection()['original_if_evidence']['state_unchanged'])
        # offset_ does not affect score_samples, so the digest catches lineage
        # mutation that score replay alone cannot detect.
        np.testing.assert_array_equal(restored.baseline_raw_scores(self.frame),self.scorer.baseline_raw_scores(self.frame))
        restored=deepcopy(self.scorer);restored.baseline_estimator_.estimators_[0].tree_.threshold[0]+=.01
        self.assertFalse(restored.inspection()['original_if_evidence']['state_unchanged'])

    def test_semantic_hash_ignores_only_padding_and_delimits_nested_values(self):
        dtype=np.dtype({'names':['a','b'],'formats':['u1','f8'],'offsets':[0,8],'itemsize':16})
        first=np.zeros(2,dtype=dtype);second=first.copy()
        second.view('u1').reshape(2,16)[:,1:8]=127
        self.assertEqual(baseline_state_digest(first),baseline_state_digest(second))
        second['b'][0]=1
        self.assertNotEqual(baseline_state_digest(first),baseline_state_digest(second))
        self.assertNotEqual(baseline_state_digest(['a','bc']),baseline_state_digest(['ab','c']))
        self.assertNotEqual(baseline_state_digest({'a':{'b':1},'c':2}),baseline_state_digest({'a':{'b':1,'c':2}}))

    def test_invalid_estimators_width_named_schema_and_duplicate_channels_rejected(self):
        with self.assertRaises(ValueError):BaselineEvidenceHGBScorer(self.channels,object())
        with self.assertRaises(NotFittedError):BaselineEvidenceHGBScorer(self.channels,IsolationForest())
        wrong=IsolationForest(n_estimators=2,random_state=3).fit(np.ones((30,3)))
        with self.assertRaises(ValueError):BaselineEvidenceHGBScorer(self.channels,wrong)
        named=IsolationForest(n_estimators=2,random_state=3).fit(pd.DataFrame(np.ones((30,4*len(self.channels))),columns=[f'wrong{i}' for i in range(4*len(self.channels))]))
        with self.assertRaises(ValueError):BaselineEvidenceHGBScorer(self.channels,named)
        with self.assertRaises(ValueError):BaselineEvidenceHGBScorer(['a','a'],None)
        with self.assertRaises(ValueError):self.scorer.baseline_features(pd.concat([self.frame,self.frame[['a']]],axis=1))

    def test_empty_short_constant_and_single_channel_inputs(self):
        for n in (0,1,14):
            frame=self.frame.iloc[:n];self.assertEqual(self.scorer.baseline_features(frame).shape,(n,2));self.assertFalse(self.scorer.baseline_observed(frame).any())
        constant=pd.DataFrame({'a':np.ones(400)});labels=np.zeros(400,np.int8);estimator=fitted_if(constant,labels)
        scorer=BaselineEvidenceHGBScorer(['a'],estimator).fit(constant,labels)
        self.assertFalse(scorer.conditional_supported_);self.assertTrue(scorer.baseline_observed(constant)[14:].all())
        self.assertTrue(np.isfinite(scorer.baseline_features(constant)).all());self.assertEqual(scorer.features(constant)[0].shape[1],len(scorer.feature_names_))

    def test_inspection_declares_in_sample_and_numeric_context_limits(self):
        info=self.scorer.inspection();contract=info['feature_contract']['original_if_evidence'] if 'feature_contract' in info else self.scorer.feature_contract_['original_if_evidence']
        self.assertTrue(info['original_if_evidence']['in_sample_training_representation']);self.assertFalse(info['original_if_evidence']['cross_fitted'])
        self.assertFalse(info['original_if_evidence']['if_fitted_here']);self.assertIn('not cross-fitted',contract['training_scope'])
        self.assertIn('cropping15/1441',contract['numeric_context_limitation']);self.assertEqual(contract['maximum_lookback_samples'],1440)
        self.assertEqual(info['original_if_evidence']['estimator_parameters'],self.estimator.get_params(deep=False))


if __name__=='__main__':unittest.main()
