"""Synthetic temporal-boundary, freeze and pretest-access guards."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
from ml.gecco_v16 import development as d
from ml.gecco_v16 import test as outer


class ExecutionTests(unittest.TestCase):
    def test_geometry_is_label_free_strictly_forward_and_calibration_adjacent(self):
        for n in (24466,27913,132480,352800):
            previous=n//4
            for fold in d.geometry(n):
                self.assertEqual(fold['forecast'][0],previous)
                self.assertEqual(fold['fit'][0],0)
                self.assertEqual(fold['fit'][1],3*previous//5)
                self.assertEqual(fold['calibration_bounds'][0],fold['fit'][1])
                self.assertEqual(fold['calibration_bounds'][-1],previous)
                self.assertTrue(all(a<b for a,b in zip(fold['calibration_bounds'][:-1],fold['calibration_bounds'][1:])))
                previous=fold['forecast'][1]
            self.assertEqual(previous,n)

    def test_disk_guard_never_removes_existing_files(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'evidence').write_text('retain')
            class Usage:free=d.RESERVE-1
            with patch.object(d.shutil,'disk_usage',return_value=Usage()),self.assertRaises(RuntimeError):d.guard(p)
            self.assertEqual((p/'evidence').read_text(),'retain')

    def test_inner_seal_records_actual_files_without_self_reference(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);(p/'teacher').write_bytes(b'trained-fixture')
            record={'supported':False,'geometry':{'fit':[0,500]}}
            d.seal_inner(p,record);sealed=json.loads((p/'complete.json').read_text())
            self.assertEqual(sealed['record'],record)
            self.assertEqual(sealed['files'],{'teacher':d.sha(p/'teacher')})

    def test_missing_independent_pretest_pass_never_opens_outer_source(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            for filename,data in [('plan.json',{}),('policies-frozen.json',{}),('pretest-audit.json',{'passed':False})]:d.write(p/filename,data)
            with patch.object(outer,'verify'),patch.object(outer,'verify_freeze'), \
                 patch.object(outer.prior,'cases',side_effect=AssertionError('no source access')) as loader:
                with self.assertRaises(ValueError):outer.run(p)
            loader.assert_not_called();self.assertFalse((p/'test-started.json').exists())

    def test_incomplete_policy_set_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d.write(p/'plan.json',{})
            for frozen in ({},{'all19_calibration_complete':True,'outer_test_numerical_arrays_opened':False,
                              'plan_sha256':d.sha(p/'plan.json'),'policies':{}}):
                with self.assertRaises(ValueError):outer.verify_freeze(p,{},frozen)


if __name__=='__main__':unittest.main()
