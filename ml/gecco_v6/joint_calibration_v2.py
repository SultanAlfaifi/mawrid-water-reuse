"""Past-only local-change rescue added to an already calibrated suppression path.

Development V6: all GECCO outcomes are already disclosed. No file reads here.
Preserve original confirmed event identities on the actual combined output.
Normal exposure and availability are identical to the immutable baseline.
"""
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'gecco_v5'))
from calibration import _gate, _stats, _comparison, POLICIES


def combine(base, seed, scores=None, threshold=None, policy='instant'):
    b=np.asarray(base);p=np.asarray(seed)
    if b.ndim!=1 or p.shape!=b.shape or b.dtype.kind not in 'biu' or p.dtype.kind not in 'biu':
        raise ValueError('Equal integer baseline and seed arrays required')
    if not np.isin(b,[-1,0,1]).all() or not np.isin(p,[-1,0,1]).all():raise ValueError('Invalid prediction')
    if not np.array_equal(b<0,p<0):raise ValueError('Seed must preserve baseline availability')
    out=p.astype(np.int8,copy=True)
    if scores is None:return out
    s=np.asarray(scores,float)
    if s.shape!=b.shape or not np.isfinite(threshold):raise ValueError('Invalid rescue scores/threshold')
    rescue=_gate(s,float(threshold),policy)
    # Past persistence cannot extend a rescue after current evidence clears.
    rescue[~np.isfinite(s)|(s<float(threshold))]=0
    out[(b>=0)&(rescue==1)]=1
    return out


def predict(base,seed,components,selected):
    chosen_seed=np.asarray(seed) if selected['seed']=='guarded' else np.asarray(base)
    if selected['rescue'] is None:return combine(base,chosen_seed)
    return combine(base,chosen_seed,components[selected['rescue']],selected['threshold'],selected['policy'])


def calibrate(blocks,*,cadence_seconds=60,min_events=5,min_eventful_blocks=2,
              min_normal_minutes_per_block=1440,min_total_normal_minutes=5760,
              min_observed_blocks=2,min_new_events=2,min_new_eventful_blocks=2):
    if not blocks or not np.isfinite(cadence_seconds) or cadence_seconds<=0:raise ValueError('Blocks and finite positive cadence required')
    minima=(min_events,min_eventful_blocks,min_normal_minutes_per_block,min_total_normal_minutes,min_observed_blocks,min_new_events,min_new_eventful_blocks)
    if any(not np.isfinite(v) or v<=0 for v in minima):raise ValueError('All evidence minima must be finite and positive')
    keys=list(blocks[0]['scores'])
    last=None
    for b in blocks:
        y=np.asarray(b['labels']);base=np.asarray(b['baseline']);seed=np.asarray(b['guarded'])
        if y.ndim!=1 or not len(y) or y.dtype.kind not in 'biu' or not np.isin(y,[0,1]).all():raise ValueError('Binary labels required')
        combine(base,seed)
        if base.shape!=y.shape or list(b['scores'])!=keys or any(np.asarray(v).shape!=y.shape for v in b['scores'].values()):raise ValueError('Mismatched arrays')
        if last is not None and b['source_start']!=last:raise ValueError('Nonadjacent calibration blocks')
        last=b['source_start']+len(y)
    y=np.concatenate([b['labels'] for b in blocks]);base=np.concatenate([b['baseline'] for b in blocks])
    ref=_stats(y,base,cadence_seconds)
    refs=[_stats(b['labels'],b['baseline'],cadence_seconds) for b in blocks]
    qualified=[i for i,r in enumerate(refs) if r['normal_observed_seconds']>=60*min_normal_minutes_per_block]
    enough_exposure=len(qualified)>=min_observed_blocks and sum(refs[i]['normal_observed_seconds'] for i in qualified)>=60*min_total_normal_minutes
    # Rescue learns from labeled events including those missed by the baseline.
    # The guarded suppression retains its own original reference-event safeguards.
    enough_events=ref['true_events']>=min_events and sum(r['true_events']>0 for r in refs)>=min_eventful_blocks
    evidence={'reference':ref,'blocks':refs,'qualified_blocks':qualified,'enough_exposure':bool(enough_exposure),
              'enough_labeled_events':bool(enough_events),'min_events':min_events,'min_eventful_blocks':min_eventful_blocks,
              'min_new_events':min_new_events,'min_new_eventful_blocks':min_new_eventful_blocks,
              'normal_minutes_per_block':min_normal_minutes_per_block,'total_normal_minutes':min_total_normal_minutes}
    trials=[]
    bounds=np.r_[0,np.cumsum([len(b['labels']) for b in blocks])]
    seed_stats={name:_stats(y,np.concatenate([b[name] for b in blocks]),cadence_seconds) for name in ('baseline','guarded')}
    def assess(seed,recipe=None,threshold=None,policy='instant'):
        choice={'seed':seed,'rescue':recipe,'threshold':threshold,'policy':policy}
        pred=[predict(b['baseline'],b['guarded'],b['scores'],choice) for b in blocks]
        whole=_comparison(y,base,np.concatenate(pred),cadence_seconds)
        parts=[_comparison(b['labels'],b['baseline'],p,cadence_seconds) for b,p in zip(blocks,pred)]
        new=set(whole['candidate']['confirmed_event_ids'])-set(whole['baseline']['confirmed_event_ids'])
        new_over_seed=set(whole['candidate']['confirmed_event_ids'])-set(seed_stats[seed]['confirmed_event_ids'])
        rescue_new=new & new_over_seed
        # One global event provides evidence only in its first detection block.
        times=dict(zip(whole['candidate']['confirmed_event_ids'],whole['candidate']['confirmed_times']))
        rescue_blocks={int(np.searchsorted(bounds,times[event_id],side='right')-1) for event_id in rescue_new}
        lost=whole['lost_baseline_event_ids']
        retains=not lost and all(not p['lost_baseline_event_ids'] for p in parts)
        no_delay=all(d['extra_delay_seconds']<=0 for p in [whole]+parts for d in p['paired_extra_delays'])
        # Check all blocks for absolute false runs/time, even short blocks.
        # Large enough exposure remains an independent evidence gate.
        fp_ok=all(p['candidate']['fp']<=p['baseline']['fp'] and p['candidate']['false_positive_runs']<=p['baseline']['false_positive_runs'] for p in [whole]+parts)
        new_ok=recipe is None or (len(rescue_new)>=min_new_events and len(rescue_blocks)>=min_new_eventful_blocks)
        feasible=retains and no_delay and fp_ok and new_ok and whole['hidden_baseline_rows']==0
        if recipe is not None:feasible=feasible and enough_exposure and enough_events
        c=whole['candidate']
        result={**choice,'feasible':bool(feasible),'events':c['confirmed_events'],'new_event_ids':sorted(new),
                'new_over_seed_event_ids':sorted(new_over_seed),'rescue_new_event_ids':sorted(rescue_new),
                'new_eventful_blocks':len(rescue_blocks),'lost_event_ids':lost,
                'retains_per_block':retains,'no_added_delay':no_delay,'no_added_false_alarms':fp_ok,
                'fp':c['fp'],'false_runs':c['false_positive_runs']}
        trials.append(result)
    assess('baseline');assess('guarded')
    if enough_exposure and enough_events:
        for recipe in keys:
            a=np.concatenate([b['scores'][recipe] for b in blocks]);finite=a[np.isfinite(a)]
            if not len(finite):continue
            thresholds=np.unique(np.r_[np.quantile(finite,np.linspace(.90,1,101)),np.nextafter(finite.max(),np.inf)])
            for seed in ('baseline','guarded'):
                for policy in POLICIES:
                    for threshold in thresholds:assess(seed,recipe,float(threshold),policy)
    feasible=[r for r in trials if r['feasible']]
    # No rescue is preferred to a needless extra channel. Threshold tie-break
    # chooses the most conservative calibrated operating point.
    selected=min(feasible,key=lambda r:(-r['events'],r['false_runs'],r['fp'],r['rescue'] is not None,
                                        -(r['threshold'] or 0),r['policy']!='instant',r['seed']!='baseline'))
    return {**selected,'evidence':evidence,'status':'rescue_selected' if selected['rescue'] else 'rescue_off'},trials
