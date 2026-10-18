"""Temporally certified <=120-second confirmation on disclosed V7 scores.

No model is refitted. All HGB models/raw scores are reused from completed
run02, with checksummed lineage. Only PAST calibration labels choose the new
alarm operating point. Every outer result is retained, including regressions.
This is a development attempt, not a new independent test or deployment.
"""
from pathlib import Path
import argparse
import json
import shutil
import sys
import time

import joblib
import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from ml.gecco_v7 import development_v2 as prior_runner
from ml.gecco_v7.development_v2 import ROOT, now, sha, write, verify, comparisons, totals
from ml.gecco_v7.calibration_certified import calibrate, predict
from ml.gecco_v7.evidence import separate_scores


def delayed_noninferior(result):
    before, after = result['baseline'], result['candidate']
    return bool(not result['lost_baseline_event_ids'] and result['sensor_availability_equal']
                and all(item['extra_delay_seconds'] <= 120 for item in result['paired_extra_delays'])
                and after['false_positive_runs'] <= before['false_positive_runs']
                and after['fp'] <= before['fp'])


def assess(labels, baseline, reference, candidate):
    result = comparisons(labels, baseline, reference, candidate)
    for comparison in result.values():
        comparison['noninferior_zero_extra_delay'] = comparison['noninferior']
        comparison['noninferior'] = delayed_noninferior(comparison)
        comparison['maximum_allowed_extra_delay_seconds'] = 120
        comparison['maximum_observed_paired_extra_delay_seconds'] = max(
            (item['extra_delay_seconds'] for item in comparison['paired_extra_delays']), default=None)
    return result


def summarize(periods, sources):
    result = {}
    for key in ('if_vs_v6', 'if_vs_v7', 'v6_vs_v7'):
        pool = [source[key] for source in sources.values()]
        parts = [period['comparisons'][key] for period in periods]
        before, after = [totals([part[model] for part in pool]) for model in ('baseline', 'candidate')]
        checks = {
            'all_prespecified_cases_complete': len(periods) == 19,
            'all_periods_and_source_pools_noninferior_with_120s_limit': all(p['noninferior'] for p in parts + pool),
            'strictly_more_pooled_events': after['confirmed_events'] > before['confirmed_events'],
            'strictly_fewer_pooled_false_runs': after['false_positive_runs'] < before['false_positive_runs'],
            'event_gain_in_at_least_two_periods': sum(bool(p['new_candidate_event_ids']) for p in parts) >= 2,
            'false_run_reduction_in_at_least_two_periods': sum(p['candidate']['false_positive_runs'] < p['baseline']['false_positive_runs'] for p in parts) >= 2,
        }
        result[key] = {'baseline': before, 'candidate': after, 'checks': checks,
                       'noninferior_periods': sum(p['noninferior'] for p in parts), 'periods': len(parts),
                       'event_gain_periods': sum(bool(p['new_candidate_event_ids']) for p in parts),
                       'false_run_reduction_periods': sum(p['candidate']['false_positive_runs'] < p['baseline']['false_positive_runs'] for p in parts),
                       'maximum_observed_paired_extra_delay_seconds': max(
                           (d['extra_delay_seconds'] for p in pool + parts for d in p['paired_extra_delays']), default=None),
                       'lost_positive_alarm_rows_descriptive': sum(p['lost_positive_alarm_rows'] for p in pool),
                       'passes_declared_development_gate': all(checks.values())}
    return result


def code_paths():
    return sorted(set(prior_runner.code_paths() + [ROOT / 'ml/gecco_v7' / name for name in
                  ('recalibrate_delayed.py', 'calibration_delayed.py', 'evidence.py', 'runtime_delayed.py',
                   'recalibrate_certified.py', 'calibration_certified.py', 'runtime_certified.py')]))


def execute(parent, out):
    parent_results = json.loads((parent / 'results.json').read_text())
    if parent_results.get('complete_cases') != 19 or not parent_results.get('all_prespecified_cases_complete'):
        raise ValueError('Completed19-case parent results required; cannot use an incomplete attempt')
    parent_plan = json.loads((parent / 'plan.json').read_text()); verify(parent_plan)
    parent_audit = json.loads((parent / 'audit.json').read_text())
    if parent_audit.get('passed') is not True:
        raise ValueError('A passing independent parent replay audit is required')
    expected_names = {p.name for p in parent.iterdir() if p.is_dir() and (p / 'freeze.json').is_file()}
    actual_names = [item['case'] for item in parent_results['periods']]
    if len(actual_names) != 19 or len(set(actual_names)) != 19 or set(actual_names) != expected_names:
        raise ValueError('Parent case identities must match all 19 frozen cases exactly')
    parent_lineage = {name: sha(parent / name) for name in ('plan.json', 'results.json', 'audit.json')}
    out.mkdir(parents=True, exist_ok=False)
    paths = code_paths()
    plan = {'created_at_utc': now(), 'attempt': 'run04_hgb_temporal_certification_120s',
            'user_preference': 'Explicit user reply permits testing alarm confirmation up to two minutes; no3D/valve integration.',
            'development_only': True, 'fresh_validation': False, 'expected_cases': 19,
            'parent_run': str(parent.relative_to(ROOT)), 'parent_plan_sha256': sha(parent / 'plan.json'),
            'parent_results_sha256': sha(parent / 'results.json'),
            'parent_audit_sha256': parent_lineage['audit.json'], 'parent_audit_passed': True,
            'code_sha256': {str(path.relative_to(ROOT)): sha(path) for path in paths},
            'input_sha256': parent_plan['input_sha256'],
            'method': 'Reuse fixed run02 HGB models and raw scores. Unchanged run03 causal <=120s confirmation and contemporaneously corroborated rescue. Change only calibration: choose from first two past blocks, freeze the single candidate internally, then certify against the two subsequent past blocks. Failed or unsupported certification returns the unchanged V6 reference; no alternate candidate search or retuning on certification.',
            'calibration': 'Four chronological past blocks: first2 selection, last2 certification. Selection uses unchanged run03 grid/evidence/constraints. Certification independently requires original event-ID retention, availability, paired event delay<=120s, no FPcount or FPduration increases in either block or their pool. Pure confirmation seed independently retains events/delay so rescue cannot conceal its losses. Adequate certification evidence uses >=5 known-onset events across>=2blocks and >=5760 known-normal minutes across>=2blocks each>=1440min. Rescue must add positive coverage to>=2original events across>=2certification blocks and add no known-normal alarm rows relative to its pure seed. All results retain TP-row losses descriptively. This split is internal development on already disclosed data.',
            'acceptance': 'All19periods and eachcontiguoussourcepool preserve reference events andavailability, pairedextra delay<=120s, noFPcount/time increase. Pooled moreevents/fewerFPruns, each gain in>=2periods. Compare againstbothoriginalIF andV6. Fullholdout disclosure; no claimfresh.',
            'no_model_refit': True, 'cadence_seconds': 60, 'maximum_confirmation_seconds': 120,
            'certification_scope': 'Only the new additive V7 policy is selected on the first2 blocks and certified on the last2. Its fixed V6 reference was previously calibrated on all4 blocks, so this is conditional policy certification, not a fully independent pipeline holdout.',
            'boundary_veto': 'Both the pure confirmation seed and combined candidate must additionally pass original-axis event-ID, availability, paired delay<=120s and FPcount/time checks across all4 blocks together; no retuning after any failed veto.',
            'deployment_approved': False, 'three_d_connected': False}
    for path in paths:
        dest = out / 'source' / path.relative_to(ROOT); dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, dest)
    write(out / 'plan.json', plan)
    periods = []; sources_rows = {}
    for item in parent_results['periods']:
        started = time.perf_counter(); verify(plan)
        name = item['case']; source = parent / name; dest = out / name; dest.mkdir()
        frozen = json.loads((source / 'freeze.json').read_text())
        source_hashes = {filename: sha(source / filename) for filename in
                         ('bundle.joblib', 'freeze.json', 'calibration_scores.csv.gz', 'predictions.csv.gz')}
        assert source_hashes['bundle.joblib'] == frozen['bundle_sha256']
        prior = ROOT / frozen['prior_folder']
        for filename, digest in frozen['prior_sha256'].items():
            assert sha(prior / filename) == digest, 'V6 cached input changed'
        bundle = joblib.load(source / 'bundle.joblib')
        assert bundle['version'] == 'v7_hgb_guarded_v2'
        assert bundle['max_fit_index'] == frozen['train'][1] - 1
        assert bundle['max_calibration_index'] == frozen['test'][0] - 1
        cal_rows = pd.read_csv(source / 'calibration_scores.csv.gz', float_precision='round_trip')
        local_rows = pd.read_csv(prior / 'calibration_scores.csv.gz', float_precision='round_trip')
        np.testing.assert_array_equal(cal_rows.sample_index, local_rows.sample_index)
        np.testing.assert_array_equal(cal_rows.sample_index, np.arange(frozen['calibration_starts'][0], frozen['test'][0]))
        local = {key: local_rows[key].to_numpy() for key in ('level', 'jump', 'sustained')}
        masks = separate_scores(local, cal_rows.long_context.to_numpy())
        np.testing.assert_allclose(masks['guarded_long_context'], cal_rows.guarded_long_context, rtol=0, atol=0, equal_nan=True)
        cal_rows['rescue_long_context'] = masks['rescue_long_context']
        starts = frozen['calibration_starts']; bounds = [value - starts[0] for value in starts + [frozen['test'][0]]]
        blocks = []
        for index, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
            rows = cal_rows.iloc[a:b]
            blocks.append({'labels': rows.label.to_numpy(np.int8), 'reference': rows.reference.to_numpy(np.int8),
                           'long_scores': rows.long_context.to_numpy(), 'rescue_scores': rows.rescue_long_context.to_numpy(),
                           'source_start': starts[index]})
        selected, trials = calibrate(blocks, cadence_seconds=60)
        cal_rows['candidate'] = np.concatenate([predict(block['reference'], block['long_scores'], selected,
                                                        rescue_scores=block['rescue_scores']) for block in blocks])
        cal_rows.to_csv(dest / 'calibration_scores.csv.gz', index=False)
        pd.DataFrame(trials).to_csv(dest / 'calibration_trials.csv.gz', index=False)
        bundle = {**bundle, 'version': 'v7_hgb_temporally_certified_120s', 'selected': selected}
        joblib.dump(bundle, dest / 'bundle.joblib', compress=3)
        shutil.copy2(source / 'model_inspection.json', dest / 'model_inspection.json')
        write(dest / 'freeze.json', {**frozen, 'frozen_at_utc': now(), 'plan_sha256': sha(out / 'plan.json'),
                                    'bundle_sha256': sha(dest / 'bundle.joblib'), 'selected': selected,
                                    'parent_folder': str(source.relative_to(ROOT)), 'parent_sha256': source_hashes,
                                    'training_reused_without_refit': True})
        # Disclosed outer scores are accessed only after the new selection freeze.
        test = pd.read_csv(source / 'predictions.csv.gz', float_precision='round_trip')
        cached = pd.read_csv(prior / 'predictions.csv.gz', float_precision='round_trip')
        np.testing.assert_array_equal(test.sample_index, cached.sample_index)
        for filename, digest in source_hashes.items():
            assert sha(source / filename) == digest, 'Parent artifact changed'
        mask = separate_scores({key: cached[key].to_numpy() for key in ('level', 'jump', 'sustained')}, test.long_context.to_numpy())
        test['rescue_long_context'] = mask['rescue_long_context']
        test['candidate'] = predict(test.reference.to_numpy(np.int8), test.long_context.to_numpy(), selected,
                                    rescue_scores=test.rescue_long_context.to_numpy())
        test.to_csv(dest / 'predictions.csv.gz', index=False)
        result = {'case': name, 'source': item['source'], 'development_only': True, 'selected': selected,
                  'comparisons': assess(*(test[column].to_numpy(np.int8) for column in ('label', 'baseline', 'reference', 'candidate'))),
                  'seconds': time.perf_counter() - started}
        write(dest / 'results.json', result); periods.append(result); sources_rows.setdefault(item['source'], []).append(test)
        brief = result['comparisons']['v6_vs_v7']
        print(json.dumps({'case': name, 'completed': True, 'events': [brief[m]['confirmed_events'] for m in ('baseline', 'candidate')],
                          'false_runs': [brief[m]['false_positive_runs'] for m in ('baseline', 'candidate')],
                          'lost_events': len(brief['lost_baseline_event_ids']), 'maximum_extra_delay_seconds': brief['maximum_observed_paired_extra_delay_seconds'],
                          'noninferior_with_120s': brief['noninferior'], 'seconds': round(result['seconds'], 2)}), flush=True)
    sources = {}
    for name, parts in sources_rows.items():
        whole = pd.concat(parts, ignore_index=True)
        assert (np.diff(whole.sample_index) == 1).all()
        sources[name] = assess(*(whole[column].to_numpy(np.int8) for column in ('label', 'baseline', 'reference', 'candidate')))
    verify(plan)
    for filename, digest in parent_lineage.items():
        assert sha(parent / filename) == digest, 'Parent plan, results, or audit changed during recalibration'
    result = {'completed_at_utc': now(), 'development_only': True, 'fresh_validation': False,
              'complete_cases': len(periods), 'expected_cases': 19, 'all_prespecified_cases_complete': len(periods) == 19,
              'maximum_allowed_extra_delay_seconds': 120, 'periods': periods, 'sources': sources,
              'summary': summarize(periods, sources)}
    write(out / 'results.json', result)
    print(json.dumps({'completed': True, 'cases': len(periods), 'summary': result['summary']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--parent', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); execute(args.parent.resolve(), args.output.resolve())
