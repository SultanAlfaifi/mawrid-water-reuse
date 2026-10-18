"""Synthetic-only boundary, evidence, accounting and failure-path tests."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from ml.gecco_v16_audits import replay as audit
from ml.gecco_v16_audits.decisions import context_oracle, weight_oracle


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False))


class FittedStub:
    classes_ = np.array([0,1], np.int8)
    n_iter_ = 100
    def __init__(self, width): self.n_features_in_ = width
    def get_params(self, deep=False): return dict(audit.HGB_PARAMS)
    def predict_proba(self, matrix):
        scores = np.clip(.4 + .05 * matrix[:,0], 0, 1)
        return np.column_stack((1-scores,scores))


def head_fixture():
    n = 500; y = np.zeros(n,np.int8); y[100:111] = 1; y[350:361] = 1; y[210:214] = -1
    a = np.zeros(n,np.int8); b = a.copy()
    for i in range(4,n-4,5): a[i:i+2]=1; b[i+1:i+4]=1
    folds = np.r_[np.zeros(250,np.int64),np.ones(250,np.int64)]
    contexts = []; anchor = np.full(n,-1,np.int64); recovery = anchor.copy()
    for start,end in ((0,250),(250,n)):
        c = context_oracle(a[start:end],b[start:end]); contexts.append(c['matrix'])
        for array,key in ((anchor,'anchor_origins'),(recovery,'recovery_origins')):
            array[start:end]=np.where(c[key]>=0,c[key]+start,-1)
    available=np.ones(n,bool); accounting=weight_oracle(y,available,folds,anchor,recovery)
    idx=np.flatnonzero(accounting['eligible']); X=np.column_stack((np.zeros((n,2),np.float32),np.concatenate(contexts)))[idx]
    targets=y[idx]; positive_folds=np.unique(folds[idx][targets==1]).tolist()
    head=SimpleNamespace(example_indices_=idx.copy(),example_fold_ids_=folds[idx].copy(),
        example_event_ids_=accounting['event_ids'][idx].copy(),example_targets_=targets.copy(),
        example_sample_weight_=accounting['sample'][idx].copy(),example_normalized_weight_=accounting['normalized'][idx].copy(),
        example_eligible_mask_=np.ones(len(idx),bool),example_matrix_sha256_=audit.array_digest(X),
        training_summary_=deepcopy(accounting['summary']),request_support_=deepcopy(accounting['summary']['request_support']),
        fit_checks_={'normal_rows':True,'positive_events':True,'positive_folds':True},fit_status_='fitted',
        model_=FittedStub(10),training_rows_=n,fit_normal_rows_=int((targets==0).sum()),
        fit_positive_rows_=int((targets==1).sum()),fit_events_=2,fit_positive_folds_=positive_folds,
        feature_names_=['a','b']+list(audit.CONTEXT_NAMES),base_feature_names_=['a','b'])
    return head,y,X,idx,folds,accounting


def frozen_fixture(root, *, test=False):
    run=root/'run';run.mkdir();write(run/'plan.json',{'synthetic':True})
    folder=run/'case';folder.mkdir()
    choice={'anchor_threshold':None,'recovery_threshold':None,'cadence_seconds':60}
    selected={'choice':choice,'accepted':False}
    files={'bundle.joblib','selection.json','trials.json','calibration_scores.csv.gz','head_examples.npz',
        'training_axis.csv.gz','training_weights.json','inner_lineage.json','model_inspection.json'}
    for name in files:
        if name=='selection.json':write(folder/name,selected)
        else:(folder/name).write_bytes(b'synthetic opaque artifact; no source content')
    hashes={name:audit.sha(folder/name) for name in files}
    freeze={'case':'case','plan_sha256':audit.sha(run/'plan.json'),'bundle_sha256':hashes['bundle.joblib'],
        'outer_test_numerical_arrays_opened':False,'selected':selected,'artifacts_sha256':hashes}
    write(folder/'freeze.json',freeze)
    frozen={'all19_calibration_complete':True,'outer_test_numerical_arrays_opened':False,
        'plan_sha256':audit.sha(run/'plan.json'),'policies':{'case':{'freeze_sha256':audit.sha(folder/'freeze.json'),
            'bundle_sha256':hashes['bundle.joblib'],'choice':choice,'accepted':False}}}
    write(run/'policies-frozen.json',frozen)
    if test:
        for name in ('predictions.csv.gz','results.json'):(folder/name).write_text('synthetic')
    return run,frozen


class GeometryTests(unittest.TestCase):
    def test_integer_boundaries_match_declared_linspace_and_past_only(self):
        for n in list(range(16,120))+[55826,132480,320001]:
            pieces=audit.geometry(n)
            self.assertEqual([g['fold'] for g in pieces],[1,2,3])
            self.assertEqual(pieces[0]['forecast'][0],n//4)
            self.assertEqual(pieces[-1]['forecast'][1],n)
            for g in pieces:
                fit=g['fit'][1];start,end=g['forecast']
                self.assertEqual(fit,3*start//5)
                self.assertEqual(g['calibration_bounds'],np.linspace(fit,start,5,dtype=np.int64).tolist())
                self.assertEqual(g['fit'][0],0);self.assertLess(fit,start);self.assertLess(start,end)
                self.assertTrue(all(a<=b for a,b in zip(g['calibration_bounds'][:-1],g['calibration_bounds'][1:])))
                if start-fit>=4:
                    self.assertTrue(all(a<b for a,b in zip(g['calibration_bounds'][:-1],g['calibration_bounds'][1:])))
            self.assertEqual([g['forecast'][1] for g in pieces[:-1]],[g['forecast'][0] for g in pieces[1:]])

    def test_invalid_geometry_rejected(self):
        for value in (True,15,2.5,'40',None):
            with self.subTest(value=value),self.assertRaises(ValueError):audit.geometry(value)


class EvidenceTests(unittest.TestCase):
    def test_legacy_add_failure_cannot_be_discarded(self):
        checks=audit.Checks()
        with self.assertRaises(ValueError):checks.add('direct legacy failure',False,numeric=3)
        self.assertFalse(checks.records[-1]['passed'])
        self.assertEqual(checks.records[-1]['numeric_comparisons'],3)

    def test_compact_reference_record_is_json_safe_and_hash_bound(self):
        source={'mask':np.array([True,False]),'references':np.array([np.nan,1.]),'rows':np.int64(2)}
        result=audit.compact(source);json.dumps(result,allow_nan=False)
        self.assertEqual(result['mask']['true_rows'],1)
        self.assertEqual(result['references']['sha256'],audit.array_digest(source['references']))
        self.assertNotIn('values',result['references'])

    def test_boolean_axis_cannot_hide_missing_or_numeric_values(self):
        audit.Checks().bits('correct',[True,False],np.array([True,False]))
        for values in ([1,0],[1,np.nan],['True','False']):
            with self.subTest(values=values),self.assertRaises(ValueError):audit.Checks().bits('bad',values,[True,False])

    def test_mask_changes_fail_even_with_float_tolerance(self):
        c=audit.Checks();c.array('finite',[1.],[1.+5e-13],floating=True)
        for a,b in (([np.nan],[0.]),([np.inf],[-np.inf]),([1.],[1.+1e-6])):
            with self.assertRaises(ValueError):audit.Checks().array('bad',a,b,floating=True)

    def test_bitwise_matrix_and_schema_guard(self):
        a=np.array([[1.,2.]],np.float32)
        audit.Checks().exact('correct',a,a.copy())
        for other in (a.astype(float),np.nextafter(a,np.float32(np.inf)),a[:,0]):
            with self.assertRaises(ValueError):audit.Checks().exact('bad',a,other)
        with self.assertRaises(ValueError):audit.compare_table(audit.Checks(),'schema',pd.DataFrame({'y':[1]}),pd.DataFrame({'label':[1]}))

    def test_safe_relative_paths(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertEqual(audit.bounded(root,'inner_1/file'),(root/'inner_1/file').resolve())
            for name in ('../escape','/absolute'):
                with self.assertRaises(ValueError):audit.bounded(root,name)


class HeadTests(unittest.TestCase):
    def test_independent_weights_targets_and_fixed_classifier_contract(self):
        head,y,X,idx,folds,weights=head_fixture()
        result=audit.audit_head(audit.Checks(),'head',head,y,X,idx,folds,weights)
        self.assertEqual(result['fit_status'],'fitted');self.assertEqual(result['positive_events'],2)
        self.assertTrue(result['independent_current_targets_and_weights'])
        self.assertEqual(head.model_.get_params(),audit.HGB_PARAMS)

    def test_tampered_target_index_weight_context_or_support_rejected(self):
        fixture=head_fixture()
        mutations=[lambda h:h.example_targets_.__setitem__(0,1),
            lambda h:h.example_indices_.__setitem__(0,0),
            lambda h:h.example_sample_weight_.__setitem__(0,0),
            lambda h:h.example_event_ids_.__setitem__(0,77),
            lambda h:h.request_support_['anchor'].__setitem__('supported',False),
            lambda h:h.feature_names_.__setitem__(-1,'future_label'),
            lambda h:setattr(h.model_,'n_iter_',101),
            lambda h:setattr(h,'example_matrix_sha256_','bad')]
        for i,mutation in enumerate(mutations):
            head=deepcopy(fixture[0]);mutation(head)
            with self.subTest(i=i),self.assertRaises(ValueError):audit.audit_head(audit.Checks(),'bad',head,*fixture[1:])

    def test_scoring_any_active_unsupported_unknown_and_cold(self):
        h,*_=head_fixture();h.request_support_['recovery']['supported']=False
        a=np.array([0,1,1,0,0,0],np.int8);b=np.array([0,0,1,1,1,0],np.int8)
        base=np.zeros((6,2),np.float32);available=np.ones(6,bool)
        result=audit.score_matrix(h,base,available,a,b)
        self.assertTrue(np.isnan(result[:4]).all());self.assertTrue(np.isfinite(result[4]));self.assertTrue(np.isnan(result[5]))
        available[4]=False;self.assertTrue(np.isnan(audit.score_matrix(h,base,available,a,b)).all())
        h.model_=None;self.assertTrue(np.isnan(audit.score_matrix(h,base,np.ones(6,bool),a,b)).all())

    def test_fresh_block_context_reset_retains_sensor_availability(self):
        h,*_=head_fixture();base=np.zeros((6,2),np.float32);available=np.ones(6,bool)
        a=np.zeros(6,np.int8);b=np.array([0,1,1,1,0,0],np.int8)
        whole=audit.score_matrix(h,base,available,a,b)
        reset=audit.score_matrix(h,base[2:],available[2:],a[2:],b[2:])
        self.assertTrue(np.isfinite(whole[2]));self.assertTrue(np.isnan(reset).all())

    def test_score_matrix_preserves_shared_audit_records(self):
        h,*_=head_fixture();checks=audit.Checks()
        a=np.zeros(4,np.int8);b=np.array([0,1,1,0],np.int8)
        audit.score_matrix(h,np.zeros((4,2),np.float32),np.ones(4,bool),a,b,checks=checks,name='shared')
        self.assertTrue(checks.records)
        self.assertTrue(all(r['check'].startswith('shared:') for r in checks.records))


class FreezeTests(unittest.TestCase):
    def test_matching_freezes_before_any_numeric_reader(self):
        with TemporaryDirectory() as tmp,patch.object(audit,'NAMES',['case']):
            run,frozen=frozen_fixture(Path(tmp))
            with patch.object(pd,'read_csv',side_effect=AssertionError('numeric access')),patch.object(audit.joblib,'load',side_effect=AssertionError('unpickle')):
                self.assertEqual(audit.validate_frozen(run,audit.Checks(),stage='train'),frozen)
                self.assertIsNone(audit.stage_gate('train',run,audit.Checks(),frozen))

    def test_artifact_tampering_and_undeclared_files_rejected(self):
        for file in ('bundle.joblib','training_axis.csv.gz','inner_1/forecast.csv.gz'):
            with self.subTest(file=file),TemporaryDirectory() as tmp,patch.object(audit,'NAMES',['case']):
                run,_=frozen_fixture(Path(tmp));p=run/'case'/file;p.parent.mkdir(exist_ok=True);p.write_bytes(b'altered')
                with self.assertRaises(ValueError):audit.validate_frozen(run,audit.Checks(),stage='train')

    def test_missing_or_extra_case_and_changed_selection_fail(self):
        with TemporaryDirectory() as tmp,patch.object(audit,'NAMES',['case']):
            run,_=frozen_fixture(Path(tmp));(run/'extra').mkdir()
            with self.assertRaises(ValueError):audit.validate_frozen(run,audit.Checks(),stage='train')
        with TemporaryDirectory() as tmp,patch.object(audit,'NAMES',['case']):
            run,_=frozen_fixture(Path(tmp));selection=audit.read(run/'case/selection.json');selection['accepted']=True
            write(run/'case/selection.json',selection)
            with self.assertRaises(ValueError):audit.validate_frozen(run,audit.Checks(),stage='train')

    def test_pretest_refuses_started_outer_experiment(self):
        with TemporaryDirectory() as tmp,patch.object(audit,'NAMES',['case']):
            run,frozen=frozen_fixture(Path(tmp));write(run/'test-started.json',{})
            with self.assertRaises(ValueError):audit.stage_gate('train',run,audit.Checks(),frozen)

    def test_test_requires_complete_matching_pretest_and_receipt(self):
        with TemporaryDirectory() as tmp,patch.object(audit,'NAMES',['case']):
            run,frozen=frozen_fixture(Path(tmp),test=True)
            proof={'audit_version':audit.AUDIT_VERSION,'stage':'train','passed':True,'failed_checks':0,
                'complete_replayed_cases':19,'audit_script_sha256':audit.sha(audit.__file__),
                'plan_sha256':audit.sha(run/'plan.json'),'policies_sha256':audit.sha(run/'policies-frozen.json'),
                'outer_test_rows_read':0,'cases':{'case':{}},'hashes':{'plan.json':audit.sha(run/'plan.json'),
                    'policies-frozen.json':audit.sha(run/'policies-frozen.json'),'case/freeze.json':audit.sha(run/'case/freeze.json'),
                    **{'case/'+p:h for p,h in audit.read(run/'case/freeze.json')['artifacts_sha256'].items()}}}
            write(run/'pretest-audit.json',proof)
            started={'plan_sha256':proof['plan_sha256'],'policies_sha256':proof['policies_sha256'],
                'pretest_audit_sha256':audit.sha(run/'pretest-audit.json'),'one_fixed_outer_pass':True}
            write(run/'test-started.json',started)
            audit.stage_gate('test',run,audit.Checks(),frozen)
            for field,bad in (('passed',False),('complete_replayed_cases',18),('outer_test_rows_read',1),('plan_sha256','bad')):
                altered={**proof,field:bad};write(run/'pretest-audit.json',altered)
                write(run/'test-started.json',{**started,'pretest_audit_sha256':audit.sha(run/'pretest-audit.json')})
                with self.subTest(field=field),self.assertRaises(ValueError):audit.stage_gate('test',run,audit.Checks(),frozen)

    def test_test_resume_receipt_and_preserved_failure_are_not_metrics(self):
        with TemporaryDirectory() as tmp,patch.object(audit,'NAMES',['case']):
            run,_=frozen_fixture(Path(tmp),test=True);write(run/'pretest-audit.json',{'synthetic':True})
            receipt={'case':'case','plan_sha256':audit.sha(run/'plan.json'),'policies_sha256':audit.sha(run/'policies-frozen.json'),
                'pretest_audit_sha256':audit.sha(run/'pretest-audit.json'),'one_fixed_outer_pass':True,'no_retuning':True,
                'files':{n:audit.sha(run/'case'/n) for n in ('predictions.csv.gz','results.json')}}
            write(run/'case/test_case_freeze.json',receipt)
            archived=run/'case/test_unsealed_123';archived.mkdir();(archived/'predictions.csv.gz').write_text('partial synthetic')
            with patch.object(pd,'read_csv',side_effect=AssertionError('must not use incomplete result')):
                audit.validate_frozen(run,audit.Checks(),stage='test')
            self.assertEqual(set(audit.preserved_test_files(run/'case',audit.Checks())),{'test_unsealed_123/predictions.csv.gz'})
            receipt['files']['results.json']='bad';write(run/'case/test_case_freeze.json',receipt)
            with self.assertRaises(ValueError):audit.verify_test_receipt(run,'case',audit.Checks())

    def test_inner_completion_requires_all_files_unchanged(self):
        with TemporaryDirectory() as tmp:
            inner=Path(tmp);(inner/'teacher.joblib').write_bytes(b'synthetic')
            record={'geometry':audit.geometry(100)[0],'supported':False,'status':'unsupported'}
            write(inner/'complete.json',{'record':record,'files':{'teacher.joblib':audit.sha(inner/'teacher.joblib')}})
            self.assertEqual(audit.verify_inner_seal(inner,audit.Checks()),record)
            (inner/'forecast.csv.gz').write_bytes(b'unsealed')
            with self.assertRaises(ValueError):audit.verify_inner_seal(inner,audit.Checks())

    def test_failure_before_source_loading_records_fail_closed(self):
        from ml.gecco_v7 import development_v2 as source
        with TemporaryDirectory() as tmp,patch.object(audit,'verify_plan',side_effect=ValueError('changed frozen code')),patch.object(source,'cases',side_effect=AssertionError('source accessed')) as loader:
            run=Path(tmp)
            self.assertEqual(audit.execute('train',run),1);loader.assert_not_called()
            report=audit.read(run/'pretest-audit.json')
            self.assertFalse(report['passed']);self.assertEqual(report['outer_test_rows_read'],0)
            self.assertEqual(report['complete_replayed_cases'],0)


if __name__=='__main__':unittest.main()
