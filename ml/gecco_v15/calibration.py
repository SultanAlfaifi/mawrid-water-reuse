"""One compact past-only policy search; later data can veto, never reselect."""
from __future__ import annotations
from copy import deepcopy
import numpy as np
from ml.gecco_v15 import checks, runtime

QUANTILES = [0, .25, .5, .75, .9, .95, 1]


def choice(anchor=None, recovery=None):
    return {'anchor_threshold': anchor, 'recovery_threshold': recovery,
            'cadence_seconds': 60}


def _grid(values):
    values = np.asarray(values, np.float64)
    values = values[np.isfinite(values)]
    return np.unique(np.quantile(values, QUANTILES, method='linear')).tolist() if len(values) else []


def _parts(blocks, selected):
    return [runtime.components(b['v6'], b['v8'], b['scores'], selected) for b in blocks]


def evaluate(blocks, selected, *, require_exposure=True):
    blocks = checks.validate_blocks(blocks)
    parts = _parts(blocks, selected)
    seeds, finals = [p['seed'] for p in parts], [p['final'] for p in parts]
    final = checks.assess(blocks, finals)
    seed = checks.seed_assess(blocks, seeds)
    recovery = checks.recovery_evidence(blocks, seeds, finals,
                                        selected['recovery_threshold'] is not None)
    exposure = checks.exposure(blocks)
    conditions = {'joint_final': final['passed'], 'pure_seed_cost': seed['passed'],
                  'recovery_support': recovery['passed'],
                  'exposure': exposure['passed'] if require_exposure else True}
    return {'passed': all(conditions.values()), 'conditions': conditions,
            'final': final, 'seed': seed, 'recovery': recovery, 'exposure': exposure}


def _rank(trial):
    a, r = trial['choice']['anchor_threshold'], trial['choice']['recovery_threshold']
    m = trial['metrics']
    return (-m['confirmed_events'], m['false_positive_runs'], m['fp'], -m['tp'],
            int(a is not None)+int(r is not None),
            a if a is not None else -np.inf, -r if r is not None else -np.inf)


def select_earlier(blocks):
    if len(blocks) != 2:
        raise ValueError('Exactly two earlier blocks required')
    blocks = checks.validate_blocks(blocks)
    anchors = [None]+_grid(np.concatenate([b['scores'][b['v8'] == 1] for b in blocks]))
    recoveries = [None]+_grid(np.concatenate([
        b['scores'][(b['v6'] == 1) & (b['v8'] == 0)] for b in blocks]))
    trials = []
    for a in anchors:
        for r in recoveries:
            selected = choice(a, r)
            evidence = evaluate(blocks, selected)
            trials.append({'choice': selected, 'feasible': evidence['passed'],
                'conditions': evidence['conditions'],
                'metrics': evidence['final']['metrics'][0]})
    feasible = [t for t in trials if t['feasible']]
    winner = deepcopy(min(feasible, key=_rank)['choice']) if feasible else None
    return winner, trials


def calibrate(blocks):
    if len(blocks) != 4:
        raise ValueError('Exactly four adjacent past blocks required')
    blocks = checks.validate_blocks(blocks)
    proposed, trials = select_earlier(blocks[:2])
    # There is no later-data selection, including when the early set is empty.
    certificate = evaluate(blocks[2:], proposed) if proposed is not None else None
    veto = evaluate(blocks, proposed, require_exposure=False) if proposed is not None else None
    accepted = bool(proposed is not None and certificate['passed'] and veto['passed'])
    selected = deepcopy(proposed) if accepted else choice()
    final = evaluate(blocks, selected, require_exposure=False)
    return {'choice': selected, 'proposed': deepcopy(proposed), 'accepted': accepted,
        'status': ('joint_policy_supported' if accepted else 'unsupported_v8_identity_fallback'),
        'earlier_trial_count': len(trials), 'feasible_earlier_trials': sum(t['feasible'] for t in trials),
        'later_certificate': certificate, 'all_four_veto': veto, 'final_assessment': final,
        'conditional_experts_not_independent_pipeline_validation': True}, trials
