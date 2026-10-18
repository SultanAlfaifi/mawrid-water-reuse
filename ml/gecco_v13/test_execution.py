"""Synthetic subprocess/resource boundaries; no real sources or model fitting."""
from contextlib import ExitStack
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

from ml.gecco_v13 import development as d


class ExecutionTests(unittest.TestCase):
    def test_disk_reserve_boundary(self):
        with patch.object(d.shutil, 'disk_usage', return_value=SimpleNamespace(free=d.MIN_FREE_BYTES)):
            d.resource_guard(Path('.'))
        with patch.object(d.shutil, 'disk_usage', return_value=SimpleNamespace(free=d.MIN_FREE_BYTES-1)):
            with self.assertRaises(RuntimeError): d.resource_guard(Path('.'))

    def run_synthetic(self, root, fail=False):
        source = root/'input.csv'; source.write_text('synthetic byte inventory only')
        out = root/'new-run'; invoked=[]
        def child(command, *, cwd, check):
            self.assertTrue(check); self.assertEqual(cwd, root)
            self.assertEqual(command[1:4], ['-B', '-m', 'ml.gecco_v13.development'])
            name=command[-1]; invoked.append(name)
            plan=json.loads((out/'plan.json').read_text())
            self.assertEqual(plan['case_order'], d.EXPECTED_NAMES)
            self.assertEqual(plan['normal_weight_recipe']['tail_relative_weight'], 5)
            self.assertEqual(plan['normal_weight_recipe']['total_negative_mass'], .5)
            self.assertIn('V8', plan['historical_retention_requirement'])
            if fail: raise RuntimeError('synthetic subprocess failure')
            folder=out/name; folder.mkdir()
            (folder/'results.json').write_text(json.dumps({'case':name,'source':'synthetic'}))
            index=len(invoked)-1
            pd.DataFrame({'sample_index':[index], 'label':[0], 'baseline':[0],
                          'reference':[0], 'candidate':[0]}).to_csv(folder/'predictions.csv.gz',index=False)
        with ExitStack() as stack:
            for owner,key,value in ((d,'ROOT',root),(d,'code_paths',lambda:[]),
                    (d,'reference_inventory',lambda:{}),(d,'historical_inventory',lambda:{}),
                    (d,'resource_guard',lambda _:None),(d,'verify',lambda _:None),
                    (d,'assess',lambda *_:{'synthetic':True}),
                    (d,'summarize',lambda *_:{'synthetic':True}),
                    (d.prior,'WATERHUB_ADAPTED',source),(d.subprocess,'run',child)):
                stack.enter_context(patch.object(owner,key,value))
            if fail:
                with self.assertRaises(RuntimeError): d.execute(out)
            else:
                d.execute(out)
                with self.assertRaises(FileExistsError): d.execute(out)
        return out,invoked

    def test_each_of19_cases_runs_in_fresh_process_before_whole_scope_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            out,invoked=self.run_synthetic(Path(temporary))
            self.assertEqual(invoked,d.EXPECTED_NAMES)
            result=json.loads((out/'results.json').read_text())
            self.assertTrue(result['all_prespecified_cases_complete'])
            self.assertEqual(result['complete_cases'],19)
            self.assertTrue(result['acceptance_evaluation_pending_independent_audit_and_historical_comparison'])

    def test_child_failure_cannot_produce_complete_run_or_silently_continue(self):
        with tempfile.TemporaryDirectory() as temporary:
            out,invoked=self.run_synthetic(Path(temporary),fail=True)
            self.assertEqual(invoked,[d.EXPECTED_NAMES[0]])
            self.assertFalse((out/'results.json').exists())
            failure=json.loads((out/'failed_case.json').read_text())
            self.assertEqual(failure['case'],d.EXPECTED_NAMES[0])


if __name__ == '__main__': unittest.main()
