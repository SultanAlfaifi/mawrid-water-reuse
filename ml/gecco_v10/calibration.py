"""Past-only pulse-retaining confirmation with optional bounded pending release.

Only the first two blocks select an operating point. The later pair and the
all-four original-axis veto can reject it, never select another. The unchanged
V6 reference is always available. Positive-pulse coverage supplements, never
replaces, original event IDs, actual paired event delay, availability and false
cost constraints. No source IO, fitting, labels at inference, or alarm backdating.
"""
from __future__ import annotations

from copy import deepcopy
import numpy as np

from ml.gecco_v7 import calibration_delayed as delayed
from ml.gecco_v7 import calibration_certified as certified
from ml.gecco_v7.calibration import (
    _MetricContext, _grid, _rescue_mask, _ternary, POLICIES,
    MIN_RESCUE_EVENTS, MIN_RESCUE_EVENTFUL_BLOCKS, full_stats,
)

MAX_CONFIRMATION_SECONDS = 120.0


def _choice(low=None, high=None, policy='instant', confirmation_samples=0,
            cadence_seconds=60, pending_after_clear=False):
    return {**delayed._choice(low, high, policy, confirmation_samples, cadence_seconds),
            'pending_after_clear': pending_after_clear}


def _validate_choice(selected):
    low, high, policy, deadline = delayed._validate_choice(selected)
    pending = selected.get('pending_after_clear', False)
    if not isinstance(pending, (bool, np.bool_)):
        raise ValueError('pending_after_clear must be boolean')
    if pending and (low is None or not deadline):
        raise ValueError('Pending requires an active bounded confirmation path')
    return low, high, policy, deadline, bool(pending)


def _fixed_choice(selected):
    low, high, policy, deadline, pending = _validate_choice(selected)
    return _choice(low, high, policy, deadline, selected.get('cadence_seconds', 60), pending)


def _spans(mask):
    changes = np.diff(np.r_[False, mask, False].astype(np.int8))
    return np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)


def _confirmation(reference, scores, low, deadline, pending):
    """Return P, A0 and post-clear trace origins on the uncompressed row axis.

The trace stores an episode's original start only on its first post-clear
release. A release during a new reference episode does not reset the old
deadline or make the old pulse continuous. At most one cleared pending record
can release on a row for the fixed one/two-sample deadlines.
"""
    unextended = delayed._confirmed_seed(reference, scores, low, deadline)
    result = unextended.copy()
    origins = np.full(len(reference), -1, np.int64)
    if not pending or low is None or not len(reference):
        return result, unextended, origins
    starts, ends = _spans(reference == 1)
    retained = np.r_[0, np.cumsum(unextended == 1)]
    eligible = (ends-starts <= deadline) & ((retained[ends]-retained[starts]) == 0)
    starts, ends = starts[eligible], ends[eligible]
    delivered = np.zeros(len(starts), bool)
    cancelled = np.zeros(len(starts), bool)
    # All possible post-clear times are bounded by the original pulse start.
    # Future arrays are indexed only at the output row being decided; prefix
    # extension cannot change an earlier release.
    for offset in range(1, deadline+1):
        positions = starts+offset
        exists = positions < len(reference)
        valid = np.flatnonzero(exists)
        cancelled[valid] |= reference[positions[valid]] < 0
        eligible = exists & (positions >= ends) & ~delivered & ~cancelled
        possible = np.flatnonzero(eligible)
        hit = possible[np.isfinite(scores[positions[possible]]) & (scores[positions[possible]] >= low)]
        result[positions[hit]] = 1
        origins[positions[hit]] = starts[hit]
        delivered[hit] = True
    return result, unextended, origins


def predict(reference, long_scores, selected, rescue_scores=None):
    reference = _ternary(reference, 'reference')
    scores = np.asarray(long_scores, float)
    rescue = scores if rescue_scores is None else np.asarray(rescue_scores, float)
    if reference.shape != scores.shape or reference.shape != rescue.shape:
        raise ValueError('Reference, confidence and rescue arrays must align')
    low, high, policy, deadline, pending = _validate_choice(selected)
    result, _, _ = _confirmation(reference, scores, low, deadline, pending)
    if high is not None:
        result[(reference >= 0) & _rescue_mask(rescue, high, policy)] = 1
    return result


def _seed_blocks(blocks, selected):
    low, _, _, deadline, pending = _validate_choice(selected)
    return tuple(map(list, zip(*[_confirmation(b['reference'], b['long_scores'], low, deadline, pending) for b in blocks])))


def _predictions(blocks, seeds, choice):
    high=choice['high_threshold']
    predictions=[p.copy() for p in seeds]
    if high is not None:
        for b,p in zip(blocks,predictions):
            p[(b['reference'] >= 0) & _rescue_mask(b['rescue_scores'],high,choice['policy'])]=1
    return predictions


def _pulse_records(labels, reference):
    episodes=list(zip(*_spans(reference == 1)))
    segments=list(zip(*_spans(labels == 1)))
    records=[]; first=0
    for episode_id,(a,b) in enumerate(episodes,1):
        while first < len(segments) and segments[first][1] <= a: first+=1
        j=first
        while j < len(segments) and segments[j][0] < b:
            c,d=segments[j]; anchor=max(a,c)
            records.append({'episode_id':episode_id,'positive_segment_id':j+1,
                'episode_start':int(a),'episode_end_exclusive':int(b),
                'positive_segment_start':int(c),'positive_segment_end_exclusive':int(d),
                'first_positive_reference_row':int(anchor),
                'left_censored_reference_episode':bool(a == 0 or reference[a-1] < 0)})
            j+=1
    return records


def _pulse_scope(labels, reference, seed, origins, selected, source_start, records=None):
    records=_pulse_records(labels,reference) if records is None else records
    prefix=np.r_[0,np.cumsum(seed == 1)]
    cadence=selected['cadence_seconds']; within=int(np.floor(MAX_CONFIRMATION_SECONDS/cadence))
    released={}
    for at in np.flatnonzero(origins >= 0): released.setdefault(int(origins[at]),[]).append(int(at))
    failures=[]; retained=0; censored=0
    for record in records:
        a=record['episode_start']; anchor=record['first_positive_reference_row']
        # A response inside an episode must ALSO be within120s of this
        # positive-segment intersection; later unrelated coverage is not enough.
        last=min(record['positive_segment_end_exclusive'],anchor+within+1)
        inside_end=min(record['episode_end_exclusive'],last)
        kept=bool(prefix[inside_end]-prefix[anchor])
        if not kept:
            kept=any(anchor <= at < last and at >= record['episode_end_exclusive']
                     and at <= a+selected['confirmation_samples'] and seed[at] == 1
                     for at in released.get(a,[]))
        retained+=int(kept); censored+=int(record['left_censored_reference_episode'])
        if not kept: failures.append({**record,'source_episode_start':source_start+a,
            'source_positive_reference_row':source_start+anchor})
    return {'passed':not failures,'obligations':len(records),'retained_obligations':retained,
        'censored_fragment_obligations':censored,'lost_positive_reference_pulses':failures,
        'rejection_reasons':[] if not failures else ['positive_reference_pulse_not_retained_within120s_in_same_segment']}


def _pulse_assessment(blocks, seeds, traces, selected):
    labels=np.concatenate([b['labels'] for b in blocks]); reference=np.concatenate([b['reference'] for b in blocks])
    seed=np.concatenate(seeds); bounds=np.r_[0,np.cumsum([len(b['labels']) for b in blocks])]
    origin=np.concatenate([np.where(t >= 0,t+bounds[i],-1) for i,t in enumerate(traces)])
    # A reference pulse crossing a block boundary keeps one global identity.
    # Map local reset trace origins back to that identity for the global veto.
    starts=(reference == 1) & np.r_[True,reference[:-1] != 1]
    global_start=np.maximum.accumulate(np.where(starts,np.arange(len(reference)),-1))
    mask=origin >= 0; origin[mask]=global_start[origin[mask]]
    scopes=[{'scope':'pool',**_pulse_scope(labels,reference,seed,origin,selected,blocks[0]['source_start'])}]
    for i,(b,p,t) in enumerate(zip(blocks,seeds,traces)):
        scopes.append({'scope':f'block_{i}',**_pulse_scope(b['labels'],b['reference'],p,t,selected,b['source_start'])})
    reasons=[s['scope']+':'+r for s in scopes for r in s['rejection_reasons']]
    return {'passed':not reasons,'rejection_reasons':reasons,'scopes':scopes,
        'interpretation':'Observed-positive episode/segment obligations; censored fragments retained but do not add primary-event evidence. Pure confirmation path before rescue; original event-ID metrics remain independent.'}


def _added_evidence(blocks, outputs, base, active, path, cadence_seconds, context=None):
    # Same fixed original-primary-event/first-addition ownership as V7, with a
    # precomputed original-axis context during the finite candidate search.
    labels=np.concatenate([b['labels'] for b in blocks]) if context is None else context.labels
    context=_MetricContext(labels) if context is None else context
    bounds=np.r_[0,np.cumsum([len(b['labels']) for b in blocks])]
    addition=(np.concatenate(outputs) == 1)&(np.concatenate(base) != 1)
    normal=addition&(labels == 0)
    normal_by_block=[int(normal[a:b].sum()) for a,b in zip(bounds[:-1],bounds[1:])]
    positions=np.flatnonzero(addition&(context.event_ids > 0))
    ids,first=np.unique(context.event_ids[positions],return_index=True)
    owners=np.searchsorted(bounds,positions[first],side='right')-1
    checks={'no_added_known_normal_rows_global':not normal.any(),
        'no_added_known_normal_rows_in_any_block':not any(normal_by_block),
        f'at_least_two_original_{path}_coverage_events':not active or len(ids) >= MIN_RESCUE_EVENTS,
        f'{path}_first_additions_in_at_least_two_blocks':not active or len(set(owners)) >= MIN_RESCUE_EVENTFUL_BLOCKS}
    return {'active':bool(active),'path':path,'passed':all(checks.values()),'checks':checks,
        'rejection_reasons':[k for k,v in checks.items() if not v],
        'added_known_normal_rows':int(normal.sum()),'added_known_normal_rows_by_block':normal_by_block,
        'coverage_event_ids':ids.tolist(),'first_addition_blocks':sorted(map(int,set(owners))),
        'event_ownership':'original primary onset; each event belongs to its first added positive row',
        'comparison_baseline':'unextended confirmation A0' if path == 'pending' else 'pure confirmation plus pending P'}


class _FastChecks:
    def __init__(self,blocks,cadence):
        self.blocks=blocks; self.cadence=cadence
        self.labels=np.concatenate([b['labels'] for b in blocks])
        self.references=[np.concatenate([b['reference'] for b in blocks])]+[b['reference'] for b in blocks]
        self.contexts=[_MetricContext(self.labels)]+[_MetricContext(b['labels']) for b in blocks]
        self.before=[c.measure(r) for c,r in zip(self.contexts,self.references)]

    def assess(self,predictions):
        candidates=[np.concatenate(predictions)]+predictions
        metrics=[c.measure(p) for c,p in zip(self.contexts,candidates)]
        reasons=[]; paired=[]; lost=[]; all_equal=True
        for i,(before,after,r,p) in enumerate(zip(self.before,metrics,self.references,candidates)):
            scope='pool' if i == 0 else f'block_{i-1}'
            old=dict(zip(before['confirmed_event_ids'],before['confirmed_times']))
            new=dict(zip(after['confirmed_event_ids'],after['confirmed_times']))
            missing=sorted(set(old)-set(new)); lost.append(missing)
            delays=[(new[k]-t)*self.cadence for k,t in old.items() if k in new]; paired.extend(delays)
            equal=bool(np.array_equal(r >= 0,p >= 0));all_equal&=equal
            checks={'reference_event_ids_retained':not missing,
                'paired_event_delay_at_most_120_seconds':all(v <= 120 for v in delays),
                'reference_availability_unchanged':equal,'false_duration_not_increased':after['fp'] <= before['fp'],
                'false_fragments_not_increased':after['false_positive_runs'] <= before['false_positive_runs']}
            reasons.extend(scope+':'+k for k,v in checks.items() if not v)
        return {'passed':not reasons,'rejection_reasons':reasons,'metrics':metrics,
            'lost_reference_event_ids':lost[0],'lost_reference_event_blocks':[i for i,x in enumerate(lost[1:]) if x],
            'max_paired_extra_delay_seconds':float(max(paired)) if paired else None,
            'availability_equal':all_equal,'lost_positive_alarm_rows':int(((self.labels == 1)&(self.references[0] == 1)&(candidates[0] != 1)).sum())}


def _rank(trial):
    low,high=trial['low_threshold'],trial['high_threshold']
    return (-trial['events'],trial['false_runs'],trial['fp'],-trial['tp'],
        int(low is not None)+int(high is not None)+int(trial['pending_after_clear']),trial['confirmation_samples'],
        low if low is not None else -np.inf,-high if high is not None else -np.inf,
        list(POLICIES).index(trial['policy']),int(trial['pending_after_clear']))


def select_earlier(blocks,*,cadence_seconds=60):
    """Exactly two earlier blocks; pulse feasibility participates in selection."""
    if len(blocks) != 2: raise ValueError('Selection requires exactly two earlier blocks')
    blocks=delayed._validated_rescue_blocks(blocks,cadence_seconds)
    fast=_FastChecks(blocks,cadence_seconds); evidence=certified._evidence(blocks,cadence_seconds)
    evidence.update(enough_exposure=evidence['enough_observed_normal_exposure'],
        enough_labeled_events=evidence['enough_primary_event_representation'],
        allowed_confirmation_samples=delayed.allowed_confirmation_samples(cadence_seconds),
        pending_known_normal_addition_limit=0,rescue_known_normal_addition_limit=0,
        min_pending_events=MIN_RESCUE_EVENTS,min_pending_eventful_blocks=MIN_RESCUE_EVENTFUL_BLOCKS)
    trials=[]; cache={}
    def seed_info(low,deadline,pending):
        key=(low,deadline,pending)
        if key not in cache:
            choice=_choice(low,None,'instant',deadline,cadence_seconds,pending)
            seeds,unextended,traces=_seed_blocks(blocks,choice)
            check=fast.assess(seeds); pulses=_pulse_assessment(blocks,seeds,traces,choice)
            added=_added_evidence(blocks,seeds,unextended,pending,'pending',cadence_seconds,fast.contexts[0])
            cache[key]=(seeds,check,pulses,added)
        return cache[key]
    def assess(choice,rescue_masks=None):
        seeds,seed_check,pulses,pending=seed_info(choice['low_threshold'],choice['confirmation_samples'],choice['pending_after_clear'])
        predictions=[s.copy() for s in seeds]
        if rescue_masks is not None:
            for b,p,mask in zip(blocks,predictions,rescue_masks):p[(b['reference'] >= 0)&mask]=1
        final=fast.assess(predictions)
        rescue=_added_evidence(blocks,predictions,seeds,choice['high_threshold'] is not None,'rescue',cadence_seconds,fast.contexts[0])
        reasons=[]
        for name,check in (('pure_seed',seed_check),('positive_pulse',pulses),('pending',pending),('candidate',final),('rescue',rescue)):
            reasons.extend(name+':'+r for r in check['rejection_reasons'])
        m=final['metrics'][0]
        trials.append({**choice,'feasible':not reasons,'rejection_reasons':reasons,
            'events':m['confirmed_events'],'tp':m['tp'],'fp':m['fp'],'false_runs':m['false_positive_runs'],
            **{key:final[key] for key in ('lost_reference_event_ids','lost_reference_event_blocks','max_paired_extra_delay_seconds','availability_equal','lost_positive_alarm_rows')},
            'lost_positive_pulse_obligations':sum(s['obligations']-s['retained_obligations'] for s in pulses['scopes'][:1]),
            'pending_added_normal_rows':pending['added_known_normal_rows'],
            'pending_added_normal_rows_by_block':pending['added_known_normal_rows_by_block'],
            'pending_coverage_event_ids':pending['coverage_event_ids'],'pending_coverage_blocks':pending['first_addition_blocks'],
            'rescue_added_normal_rows':rescue['added_known_normal_rows'],
            'rescue_added_normal_rows_by_block':rescue['added_known_normal_rows_by_block'],
            'rescue_coverage_event_ids':rescue['coverage_event_ids'],'rescue_coverage_blocks':rescue['first_addition_blocks']})
    assess(_choice(cadence_seconds=cadence_seconds))
    if evidence['enough_exposure'] and evidence['enough_labeled_events']:
        scores=np.concatenate([b['long_scores'] for b in blocks]); reference=fast.references[0]
        rescue=np.concatenate([b['rescue_scores'] for b in blocks]); deadlines=evidence['allowed_confirmation_samples']
        lows=[None]+(_grid(scores[reference == 1],np.linspace(0,1,21)) if deadlines else [])
        highs=[None]+_grid(rescue,np.linspace(.90,1,41),above_max=True)
        for policy in POLICIES:
            masks={high:[_rescue_mask(b['rescue_scores'],high,policy) for b in blocks] for high in highs if high is not None}
            for low in lows:
                for deadline in ([0] if low is None else deadlines):
                    for pending in ([False] if low is None else [False,True]):
                        for high in highs:
                            if low is None and high is None:continue
                            if low is not None and high is not None and low > high:continue
                            assess(_choice(low,high,policy,deadline,cadence_seconds,pending),masks.get(high))
    selected=min((t for t in trials if t['feasible']),key=_rank)
    seeds,_,_=_seed_blocks(blocks,selected); predictions=_predictions(blocks,seeds,selected)
    verification=[full_stats(y,p,cadence_seconds) for y,p in
        zip([fast.labels]+[b['labels'] for b in blocks],[np.concatenate(predictions)]+predictions)]
    for a,b in zip(fast.assess(predictions)['metrics'],verification):
        for key,value in a.items():
            if value != b[key]:raise AssertionError('Fast calibration metric differs from frozen original-axis metric: '+key)
    status=('insufficient_observed_normal_exposure' if not evidence['enough_exposure'] else
            'insufficient_primary_event_representation' if not evidence['enough_labeled_events'] else
            'reference_retained' if selected['decision'] == 'reference' else 'pulse_retaining_confirmation_operating_point_selected')
    return {**selected,'status':status,'evidence':evidence,'calibration_metrics':verification[0],
        'calibration_block_metrics':verification[1:],'trial_count':len(trials)},trials


def _fixed_checks(blocks,choice,cadence):
    seeds,unextended,traces=_seed_blocks(blocks,choice); predictions=_predictions(blocks,seeds,choice)
    return {'candidate':certified._assessment(blocks,predictions,cadence),
        'pure_confirmation_seed':certified._assessment(blocks,seeds,cadence),
        'positive_reference_pulses':_pulse_assessment(blocks,seeds,traces,choice),
        'pending':_added_evidence(blocks,seeds,unextended,choice['pending_after_clear'],'pending',cadence),
        'rescue':_added_evidence(blocks,predictions,seeds,choice['high_threshold'] is not None,'rescue',cadence)}


def certify(selected,blocks,*,cadence_seconds=60):
    if len(blocks) != 2:raise ValueError('Certification requires exactly two later blocks')
    blocks=delayed._validated_rescue_blocks(blocks,cadence_seconds);choice=_fixed_choice(selected)
    if choice['cadence_seconds'] != cadence_seconds:raise ValueError('Policy/certificate cadence mismatch')
    evidence=certified._evidence(blocks,cadence_seconds);assessments=_fixed_checks(blocks,choice,cadence_seconds)
    checks={'adequate_observed_normal_exposure':evidence['enough_observed_normal_exposure'],
        'adequate_primary_event_representation':evidence['enough_primary_event_representation'],
        **{name+'_passed':check['passed'] for name,check in assessments.items()}}
    reasons=[name for name,passed in checks.items() if not passed]
    reasons.extend(name+':'+r for name,check in assessments.items() for r in check['rejection_reasons'])
    return {'passed':not reasons,'checks':checks,'rejection_reasons':reasons,'fixed_choice':choice,
        'evidence':evidence,**assessments,
        'interpretation':'Temporal veto of incremental policy conditional on V6 calibrated on all4; not independent validation of whole pipeline.'}


def calibrate(blocks,*,cadence_seconds=60):
    if len(blocks) != 4:raise ValueError('Exactly four adjacent past blocks required')
    blocks=delayed._validated_rescue_blocks(blocks,cadence_seconds)
    earlier,trials=select_earlier(blocks[:2],cadence_seconds=cadence_seconds)
    earlier=deepcopy(earlier);proposed=_fixed_choice(earlier)
    certificate=certify(proposed,blocks[2:],cadence_seconds=cadence_seconds)
    all_four=_fixed_checks(blocks,proposed,cadence_seconds)
    early=_fixed_checks(blocks[:2],proposed,cadence_seconds)
    veto={'earlier_pure_confirmation_seed':early['pure_confirmation_seed'],
        'earlier_positive_reference_pulses':early['positive_reference_pulses'],
        'earlier_pending':early['pending'],
        **{'all_four_'+name:check for name,check in all_four.items()}}
    veto_reasons=[name+':'+r for name,check in veto.items() for r in check['rejection_reasons']]
    accepted=certificate['passed'] and not veto_reasons
    final=proposed if accepted else _choice(cadence_seconds=cadence_seconds)
    status=('earlier_reference_retained' if proposed['decision'] == 'reference' else
            'temporally_certified_pulse_pending_policy_selected' if accepted else 'certification_failed_reference_retained')
    seeds,_,_=_seed_blocks(blocks,final);predictions=_predictions(blocks,seeds,final)
    labels=np.concatenate([b['labels'] for b in blocks]);metrics=full_stats(labels,np.concatenate(predictions),cadence_seconds)
    assessed=certified._assessment(blocks,predictions,cadence_seconds)
    reasons=certificate['rejection_reasons']+veto_reasons
    trials=[{**deepcopy(t),'stage':'earlier_selection'} for t in trials]
    trials.append({**proposed,'stage':'later_certification_and_global_veto','feasible':bool(accepted),'rejection_reasons':reasons})
    return {**final,'status':status,'earlier_selected':earlier,'certification':certificate,
        'global_veto':veto,'certification_passed':bool(accepted),'certification_rejection_reasons':reasons,
        'final_selected':deepcopy(final),'selection_blocks':[b['block_id'] for b in blocks[:2]],
        'certification_blocks':[b['block_id'] for b in blocks[2:]],
        'evidence':{'earlier_selection':earlier['evidence'],'later_certification':certificate['evidence']},
        'calibration_metrics':metrics,'calibration_block_metrics':[full_stats(b['labels'],p,cadence_seconds) for b,p in zip(blocks,predictions)],
        'calibration_paired_delays':assessed['scopes'][0]['paired_extra_delays'],
        'lost_positive_alarm_rows':assessed['scopes'][0]['lost_positive_alarm_rows'],
        'max_paired_extra_delay_seconds':max((s['max_paired_extra_delay_seconds'] for s in assessed['scopes'] if s['max_paired_extra_delay_seconds'] is not None),default=None),
        'trial_count':len(trials),'selection_trial_count':len(trials)-1,'certification_attempts':1,
        'events':metrics['confirmed_events'],'tp':metrics['tp'],'fp':metrics['fp'],'false_runs':metrics['false_positive_runs']},trials
