"""Tamper/incomplete-run guards before any outer test CSV access."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ml.gecco_v15 import development as d
from ml.gecco_v15.calibration import choice


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.out=Path(self.temp.name)
        d.write(self.out/'plan.json',{'fixture':True})
        self.freeze={'all19_calibration_complete':True,'outer_test_numeric_values_opened':False,
            'plan_sha256':d.sha(self.out/'plan.json'),'policies':{}}
        for name in d.NAMES:
            folder=self.out/name;folder.mkdir()
            d.write(folder/'selection.json',{'choice':choice(),'accepted':False})
            d.write(folder/'trials.json',[])
            (folder/'calibration_predictions.csv.gz').write_bytes(b'fixture-not-a-real-source')
            self.freeze['policies'][name]={'choice':choice(),'accepted':False,
                'selection_sha256':d.sha(folder/'selection.json'),
                'trials_sha256':d.sha(folder/'trials.json'),
                'calibration_predictions_sha256':d.sha(folder/'calibration_predictions.csv.gz')}

    def tearDown(self): self.temp.cleanup()

    def test_exact_complete_frozen_policies_pass(self):
        d.verify_policies(self.out,self.freeze)

    def test_missing_case_incomplete_flag_or_plan_mismatch_rejected(self):
        bad=copy.deepcopy(self.freeze);bad['policies'].pop(d.NAMES[-1])
        for f in (bad,{**self.freeze,'all19_calibration_complete':False},
                  {**self.freeze,'outer_test_numeric_values_opened':True},
                  {**self.freeze,'plan_sha256':'wrong'}):
            with self.subTest(f=list(f)),self.assertRaises(ValueError):d.verify_policies(self.out,f)

    def test_each_artifact_and_choice_is_bound(self):
        first=self.out/d.NAMES[0]
        for filename in ('selection.json','trials.json','calibration_predictions.csv.gz'):
            path=first/filename;original=path.read_bytes();path.write_bytes(original+b'changed')
            with self.subTest(filename=filename),self.assertRaises(ValueError):d.verify_policies(self.out,self.freeze)
            path.write_bytes(original)
        bad=copy.deepcopy(self.freeze);bad['policies'][d.NAMES[0]]['choice']=choice(.5,None)
        with self.assertRaises(ValueError):d.verify_policies(self.out,bad)

    def test_disk_guard_is_read_only_and_does_not_delete_evidence(self):
        marker=self.out/'keep';marker.write_bytes(b'evidence')
        class Usage:free=d.RESERVE-1
        with patch.object(d.shutil,'disk_usage',return_value=Usage()),self.assertRaises(RuntimeError):d.guard(self.out)
        self.assertEqual(marker.read_bytes(),b'evidence')


if __name__=='__main__':unittest.main()
