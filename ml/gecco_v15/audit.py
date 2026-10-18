"""Independent scalar/metric audit of V15's frozen-score policy experiment.

No production V15 inference, calibration, checks or development module is
imported. The previously audited original-axis V6 metric definitions are reused.
Calibration audit opens no outer prediction CSV. This is policy replay, not a
new raw-sensor/model/streaming validation; inherited evidence is hash-verified.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pandas as pd
from ml.gecco_v6.unknown_label_metrics import stats, comparison

ROOT = Path(__file__).resolve().parents[2]
NAMES = ([f'{y}_fold_{i}' for y in ('2017','2018') for i in range(1,7)]
         + ['2019_disclosed_test','2018-11','2018-12','2019-01','2019-02','2019-03','2019-04'])
HISTORY = ['v8','v9','v10','v11','v12','v13','v14']
PROTOCOL = 'output/ml/gecco-v15-design/protocol.json'
PROTOCOL_SHA = '5bc11ea7154a29c9f2301d2d9d652c8d38887e908c5d6aeb9983a2e3a5ca0c66'
V14_AUDIT_SHA = '09ba31b89ccf58b66b9790fd822243d18d923e2364cd73da98dcd08a3a4b0f3b'
AUDIT_VERSION = 'v15_independent_scalar_frozen_score_policy_replay_v1'
MKEYS = ('true_events','confirmed_event_ids','confirmed_times','confirmed_events','tp','fp',
         'false_positive_runs','normal_observed_rows','available_rows','fp_duration_seconds',
         'normal_observed_seconds','rows','cadence_seconds')
QUANTILES = [0,.25,.5,.75,.9,.95,1]


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def read(path): return json.loads(Path(path).read_text())
def _choice(a=None,r=None): return {'anchor_threshold':a,'recovery_threshold':r,'cadence_seconds':60}


class Evidence:
    def __init__(self): self.checks=0; self.numeric=0
    def require(self,name,condition):
        self.checks+=1
        if not condition: raise AssertionError(name)
    def array(self,name,actual,expected):
        a,b=np.asarray(actual),np.asarray(expected); self.numeric+=b.size
        self.require(name+':shape',a.shape==b.shape)
        self.require(name+':values',bool(np.array_equal(a,b,equal_nan=True)))
    def tree(self,name,actual,expected):
        # Explicit expected fields must exist; narrative-only extras are ignored.
        if isinstance(expected,dict):
            self.require(name+':mapping',isinstance(actual,dict))
            self.require(name+':required_fields',set(expected)<=set(actual))
            for k,v in expected.items(): self.tree(name+'/'+k,actual[k],v)
        elif isinstance(expected,(list,tuple)):
            self.require(name+':list',isinstance(actual,(list,tuple)))
            self.require(name+':length',len(actual)==len(expected))
            for i,(a,b) in enumerate(zip(actual,expected)): self.tree(name+'/'+str(i),a,b)
        elif isinstance(expected,(int,float,np.number)) and not isinstance(expected,(bool,np.bool_)):
            self.numeric+=1
            self.require(name+':number',isinstance(actual,(int,float,np.number)) and not isinstance(actual,(bool,np.bool_)))
            self.require(name+':value',actual==expected)
        else: self.require(name,actual==expected and (not isinstance(expected,bool) or isinstance(actual,bool)))


def scalar_components(v6,v8,scores,choice):
    """Literal chronological state machine, independent of vectorized runtime."""
    arrays=[np.asarray(x) for x in (v6,v8,scores)]
    if any(x.ndim!=1 for x in arrays) or len({x.shape for x in arrays})!=1: raise ValueError('Unequal axes')
    for a in arrays[:2]:
        if a.dtype.kind not in 'iu' or not np.isin(a,[-1,0,1]).all(): raise ValueError('Ternary integer references required')
    if arrays[2].dtype.kind not in 'iuf': raise ValueError('Real scores required')
    if choice.get('cadence_seconds')!=60 or isinstance(choice.get('cadence_seconds'),bool): raise ValueError('60-second policy required')
    low,high=choice['anchor_threshold'],choice['recovery_threshold']
    for t in (low,high):
        if t is not None and (isinstance(t,(bool,np.bool_)) or not isinstance(t,(int,float,np.number)) or not math.isfinite(t)): raise ValueError('Finite thresholds required')
    a,b,confidence=[x.tolist() for x in arrays]
    seed=np.empty(len(b),np.int8); recovery=np.empty(len(b),np.int8)
    anchor_start=None; anchor_released=False; pending=None; latched=None
    for i,(first,anchor,score) in enumerate(zip(a,b,confidence)):
        if anchor!=1:
            anchor_start=None; anchor_released=False; seed[i]=anchor
        elif low is None: seed[i]=1
        else:
            if anchor_start is None: anchor_start=i; anchor_released=False
            if not math.isfinite(score) or score>=low or i-anchor_start>=2: anchor_released=True
            seed[i]=int(anchor_released)
        recovery[i]=-1 if anchor<0 else 0
        if high is None: continue
        if first<0 or anchor<0: pending=None; latched=None; continue
        if first!=1: latched=None
        new_start=i>0 and a[i-1]==0 and first==1
        if new_start:
            pending=None
            if anchor==0: pending=i
        if pending is not None and i-pending>2: pending=None
        if pending is not None and math.isfinite(score) and score>=high:
            if first==1: latched=pending
            else: recovery[i]=1  # post-clear one-shot, even if anchor=1
            pending=None
        if latched is not None and first==1 and anchor==0: recovery[i]=1
    final=seed.copy(); final[recovery==1]=1
    return {'seed':seed,'recovery':recovery,'final':final}


def metric(y,p): return {k:v for k,v in stats(y,p,60).items() if k in MKEYS}


def _runs(values):
    start=None
    for i,v in enumerate(values):
        if v and start is None: start=i
        if not v and start is not None: yield start,i; start=None
    if start is not None: yield start,len(values)


def pulse_evidence(y,reference,prediction,source_start):
    segments=list(_runs(y==1)); obligations=0; censored=0; losses=[]
    for episode_id,(a,b) in enumerate(_runs(reference==1),1):
        for segment_id,(c,d) in enumerate(segments,1):
            if c>=b: break
            if d<=a: continue
            anchor=max(a,c); stop=min(d,anchor+3); obligations+=1
            pc=bool(a==0 or reference[a-1]<0); lc=bool(c==0 or y[c-1]!=0); censored+=int(pc or lc)
            if not np.any(prediction[anchor:stop]==1):
                losses.append({'episode_id':episode_id,'positive_segment_id':segment_id,
                    'episode_start':a,'episode_end_exclusive':b,'positive_segment_start':c,
                    'positive_segment_end_exclusive':d,'first_positive_reference_row':anchor,
                    'source_first_positive_reference_row':source_start+anchor,'last_allowed_row':stop-1,
                    'left_censored_reference_episode':pc,'left_censored_positive_segment':lc})
    return {'passed':not losses,'obligations':obligations,'retained_obligations':obligations-len(losses),
            'censored_fragment_obligations':censored,'lost_positive_reference_pulses':losses}


def scopes(blocks,predictions):
    pool={k:np.concatenate([b[k] for b in blocks]) for k in ('labels','v6','v8')}
    return [{'scope':'pool','block_id':None,'source_start':blocks[0]['source_start'],**pool,'prediction':np.concatenate(predictions)}]+[
        {'scope':'block_'+str(i),'block_id':b['block_id'],'source_start':b['source_start'],
         **{k:b[k] for k in ('labels','v6','v8')},'prediction':p} for i,(b,p) in enumerate(zip(blocks,predictions))]


def joint_assessment(blocks,predictions,seed=False):
    output=[];metrics=[];passed=True
    for s in scopes(blocks,predictions):
        y,p=s['labels'],s['prediction']; cm=metric(y,p); metrics.append(cm)
        ct=dict(zip(cm['confirmed_event_ids'],cm['confirmed_times']));refs={};checks={};union=set()
        for key in (('v8',) if seed else ('v6','v8')):
            r=s[key]; rm=metric(y,r); rt=dict(zip(rm['confirmed_event_ids'],rm['confirmed_times']));union.update(rt)
            lost=sorted(set(rt)-set(ct));paired=[{'event_id':eid,'extra_delay_seconds':float((ct[eid]-t)*60),
                'reference_confirmation_index':t,'candidate_confirmation_index':ct[eid]} for eid,t in rt.items() if eid in ct]
            check={'availability_equal':bool(np.array_equal(p>=0,r>=0)),
                'false_fragments_nonincreasing':cm['false_positive_runs']<=rm['false_positive_runs'],
                'false_duration_nonincreasing':cm['fp']<=rm['fp']}
            pulse=None
            if not seed:
                pulse=pulse_evidence(y,r,p,s['source_start'])
                check.update(event_ids_retained=not lost,paired_delay_at_most120s=all(x['extra_delay_seconds']<=120 for x in paired),
                    positive_pulse_intersections_retained=pulse['passed'])
            passed=passed and all(check.values());checks[key]=check
            refs[key]={'checks':check,'metrics':rm,'lost_reference_event_ids':lost,'paired_extra_delays':paired,
                'max_paired_extra_delay_seconds':max((x['extra_delay_seconds'] for x in paired),default=None),
                'lost_positive_alarm_rows':int(((y==1)&(r==1)&(p!=1)).sum()),'positive_pulses':pulse}
        output.append({'scope':s['scope'],'block_id':s['block_id'],'source_start':s['source_start'],
            'metrics':cm,'references':refs,'reference_union_event_ids':sorted(union),
            'lost_union_event_ids':sorted(union-set(ct)),'checks':checks})
    return {'passed':bool(passed),'metrics':metrics,'scopes':output,
            'retention_required':not seed,'pulse_retention_required':not seed,'lost_union_event_ids':output[0]['lost_union_event_ids']}


def exposure(blocks):
    y=np.concatenate([b['labels'] for b in blocks]); bounds=np.cumsum([0]+[len(b['labels']) for b in blocks])
    primary=stats(y,np.zeros(len(y),np.int8))['primary_event_intervals']
    owners=sorted({int(np.searchsorted(bounds,x['start'],side='right')-1) for x in primary})
    minutes=[int(((b['labels']==0)&(b['v6']>=0)&(b['v8']>=0)).sum()) for b in blocks]
    qualified=[i for i,n in enumerate(minutes) if n>=1440]; total=sum(minutes[i] for i in qualified)
    checks={'enough_observed_normal_exposure':len(qualified)>=2 and total>=5760,
            'enough_primary_event_representation':len(primary)>=5 and len(owners)>=2}
    return {'passed':all(checks.values()),'checks':checks,'primary_events':len(primary),'eventful_blocks':owners,
        'qualified_blocks':qualified,'qualified_block_ids':[blocks[i]['block_id'] for i in qualified],
        'observed_normal_minutes_by_block':minutes,'qualified_normal_minutes':total,
        'min_events':5,'min_eventful_blocks':2,'min_observed_blocks':2,'min_normal_minutes_per_block':1440,
        'min_total_normal_minutes':5760,'source_range':[blocks[0]['source_start'],blocks[-1]['source_start']+len(blocks[-1]['labels'])]}


def recovery_evidence(blocks,seeds,finals,active):
    y=np.concatenate([b['labels'] for b in blocks]); seed=np.concatenate(seeds); final=np.concatenate(finals)
    before,after=stats(y,seed),stats(y,final); ft=dict(zip(after['confirmed_event_ids'],after['confirmed_times']))
    gained=sorted(set(ft)-set(before['confirmed_event_ids']));bounds=np.cumsum([0]+[len(b['labels']) for b in blocks])
    records=[{'event_id':i,'first_final_confirmation_index':ft[i],
        'source_first_final_confirmation_index':blocks[0]['source_start']+ft[i],
        'owner_block':int(np.searchsorted(bounds,ft[i],side='right')-1)} for i in gained]
    owners=sorted({x['owner_block'] for x in records});added=(final==1)&(seed!=1); normal=added&(y==0)
    normal_blocks=[int(normal[a:b].sum()) for a,b in zip(bounds[:-1],bounds[1:])]
    union=set()
    for key in ('v6','v8'): union.update(stats(y,np.concatenate([b[key] for b in blocks]))['confirmed_event_ids'])
    checks={'availability_unchanged_from_seed':bool(np.array_equal(final>=0,seed>=0)),
        'seed_alarm_rows_not_removed':not bool(((seed==1)&(final!=1)).any()),
        'inactive_recovery_is_identity':active or bool(np.array_equal(seed,final)),
        'zero_added_known_normal_rows_global':not bool(normal.any()),'zero_added_known_normal_rows_each_block':not any(normal_blocks),
        'at_least_two_new_confirmed_ids_vs_seed':not active or len(gained)>=2,
        'actual_first_confirmation_in_at_least_two_blocks':not active or len(owners)>=2}
    return {'active':active,'passed':all(checks.values()),'checks':checks,'new_confirmed_event_ids':gained,
        'new_confirmed_event_records':records,'first_confirmation_blocks':owners,
        'first_confirmation_block_ids':[blocks[i]['block_id'] for i in owners],
        'restored_reference_event_ids':sorted(set(gained)&union),'novel_beyond_reference_union_event_ids':sorted(set(gained)-union),
        'added_known_normal_rows':int(normal.sum()),'added_known_normal_rows_by_block':normal_blocks,
        'added_unknown_label_rows':int((added&(y<0)).sum()),'added_positive_rows':int((added&(y==1)).sum()),
        'min_new_confirmed_events':2,'min_owning_blocks':2}


def evaluate(blocks,choice,require_exposure=True):
    parts=[scalar_components(b['v6'],b['v8'],b['scores'],choice) for b in blocks]
    seeds=[p['seed'] for p in parts];finals=[p['final'] for p in parts]
    final=joint_assessment(blocks,finals);seed=joint_assessment(blocks,seeds,True)
    recovery=recovery_evidence(blocks,seeds,finals,choice['recovery_threshold'] is not None);support=exposure(blocks)
    conditions={'joint_final':final['passed'],'pure_seed_cost':seed['passed'],'recovery_support':recovery['passed'],
                'exposure':support['passed'] if require_exposure else True}
    return {'passed':all(conditions.values()),'conditions':conditions,'final':final,'seed':seed,'recovery':recovery,'exposure':support}


def rank(trial):
    m=trial['metrics'];a,r=trial['choice']['anchor_threshold'],trial['choice']['recovery_threshold']
    return (-m['confirmed_events'],m['false_positive_runs'],m['fp'],-m['tp'],int(a is not None)+int(r is not None),
            a if a is not None else -math.inf,-r if r is not None else -math.inf)


def oracle_calibrate(blocks):
    def grid(x):
        x=np.asarray(x,np.float64);x=x[np.isfinite(x)]
        return [None]+(np.unique(np.quantile(x,QUANTILES,method='linear')).tolist() if len(x) else [])
    early=blocks[:2]
    anchors=grid(np.concatenate([b['scores'][b['v8']==1] for b in early]))
    recoveries=grid(np.concatenate([b['scores'][(b['v6']==1)&(b['v8']==0)] for b in early]))
    trials=[]
    for a in anchors:
        for r in recoveries:
            choice=_choice(a,r);e=evaluate(early,choice)
            trials.append({'choice':choice,'feasible':e['passed'],'conditions':e['conditions'],'metrics':e['final']['metrics'][0]})
    feasible=[t for t in trials if t['feasible']];proposed=min(feasible,key=rank)['choice'] if feasible else None
    cert=evaluate(blocks[2:],proposed) if proposed is not None else None
    veto=evaluate(blocks,proposed,False) if proposed is not None else None
    accepted=bool(proposed is not None and cert['passed'] and veto['passed']);choice=proposed if accepted else _choice()
    return {'choice':choice,'proposed':proposed,'accepted':accepted,
        'status':'joint_policy_supported' if accepted else 'unsupported_v8_identity_fallback',
        'earlier_trial_count':len(trials),'feasible_earlier_trials':len(feasible),'later_certificate':cert,
        'all_four_veto':veto,'final_assessment':evaluate(blocks,choice,False),
        'conditional_experts_not_independent_pipeline_validation':True},trials


def pair(y,base,candidate):
    result=comparison(y,base,candidate,60)
    fixed=(not result['lost_baseline_event_ids'] and result['sensor_availability_equal']
        and result['candidate']['false_positive_runs']<=result['baseline']['false_positive_runs']
        and result['candidate']['fp']<=result['baseline']['fp'])
    delays=[x['extra_delay_seconds'] for x in result['paired_extra_delays']]
    result.update(noninferior=bool(fixed and all(x<=120 for x in delays)),
        noninferior_zero_extra_delay=bool(fixed and all(x<=0 for x in delays)),
        lost_positive_alarm_rows=int(((y==1)&(base==1)&(candidate!=1)).sum()),
        maximum_allowed_extra_delay_seconds=120,maximum_observed_paired_extra_delay_seconds=max(delays,default=None))
    return result


def comparisons(y,baseline,v6,candidate):
    return {key:pair(y,a,b) for key,a,b in [('if_vs_v6',baseline,v6),('if_vs_v7',baseline,candidate),('v6_vs_v7',v6,candidate)]}


def totals(items):
    keys=('true_events','confirmed_events','tp','fp','fn','tn','false_positive_runs','normal_observed_seconds',
          'fp_duration_seconds','known_positive_rows','positive_unavailable_rows','rows','available_rows')
    out={k:sum(x[k] for x in items) for k in keys};ratio=lambda a,b:a/b if b else None
    out.update(confirmed_event_recall=ratio(out['confirmed_events'],out['true_events']),precision=ratio(out['tp'],out['tp']+out['fp']),
        recall_observed_positive=ratio(out['tp'],out['tp']+out['fn']),
        f1_observed_points=ratio(2*out['tp'],2*out['tp']+out['fp']+out['fn']),
        false_runs_per_day=ratio(out['false_positive_runs']*86400,out['normal_observed_seconds']))
    return out


def summary(periods,sources):
    result={}
    for key in ('if_vs_v6','if_vs_v7','v6_vs_v7'):
        pool=[s[key] for s in sources.values()];parts=[p['comparisons'][key] for p in periods]
        before,after=[totals([p[m] for p in pool]) for m in ('baseline','candidate')]
        gains=sum(bool(p['new_candidate_event_ids']) for p in parts)
        reductions=sum(p['candidate']['false_positive_runs']<p['baseline']['false_positive_runs'] for p in parts)
        checks={'all_prespecified_cases_complete':len(periods)==19,
            'all_periods_and_source_pools_noninferior_with_120s_limit':all(p['noninferior'] for p in parts+pool),
            'strictly_more_pooled_events':after['confirmed_events']>before['confirmed_events'],
            'strictly_fewer_pooled_false_runs':after['false_positive_runs']<before['false_positive_runs'],
            'event_gain_in_at_least_two_periods':gains>=2,'false_run_reduction_in_at_least_two_periods':reductions>=2}
        result[key]={'baseline':before,'candidate':after,'checks':checks,'noninferior_periods':sum(p['noninferior'] for p in parts),
            'periods':len(parts),'event_gain_periods':gains,'false_run_reduction_periods':reductions,
            'maximum_observed_paired_extra_delay_seconds':max((d['extra_delay_seconds'] for p in pool+parts for d in p['paired_extra_delays']),default=None),
            'lost_positive_alarm_rows_descriptive':sum(p['lost_positive_alarm_rows'] for p in pool),
            'passes_declared_development_gate':all(checks.values())}
    return result


def parent(version): return ROOT/f'output/ml/gecco-{version}-development/run_01'


def verify_plan(run,e):
    plan=read(run/'plan.json')
    e.tree('plan scope',plan,{'version':'v15_joint_reference_bounded_recovery','attempt':'v15_run01_frozen_score_policy_only',
        'case_order':NAMES,'expected_cases':19,'development_only':True,'fresh_validation':False,
        'all_sources_previously_disclosed':True,'no_model_fit':True,'new_raw_sensor_replay':False,
        'protocol_sha256':PROTOCOL_SHA,'no_3d_or_actuation_promotion':True})
    for group in ('code_sha256','input_sha256'):
        e.require(group+' nonempty',bool(plan.get(group)))
        for name,digest in plan[group].items():
            path=(ROOT/name).resolve();e.require('path stays in workspace',path.is_relative_to(ROOT))
            e.require('frozen '+name,sha(path)==digest)
    e.require('pinned protocol',plan['input_sha256'].get(PROTOCOL)==PROTOCOL_SHA)
    for filename in ('audit.py','runtime.py','checks.py','calibration.py','development.py'):
        e.require('audited policy source pinned:'+filename,'ml/gecco_v15/'+filename in plan['code_sha256'])
    e.require('pinned previously completed V14 audit',sha(parent('v14')/'audit.json')==V14_AUDIT_SHA)
    anchor_audit=read(parent('v14')/'audit.json')
    e.require('anchor plan matches pinned audit',sha(parent('v14')/'plan.json')==anchor_audit['hashes']['plan.json'])
    anchor_plan=read(parent('v14')/'plan.json')
    inherited={}
    for version in HISTORY:
        folder=parent(version);audit=read(folder/'audit.json');result=read(folder/'results.json')
        if version!='v14':
            for filename in ('plan.json','results.json','audit.json'):
                e.require('anchored historical lineage '+version+'/'+filename,
                    sha(folder/filename)==anchor_plan['input_sha256'][str((folder/filename).relative_to(ROOT))])
        e.require('historical audit complete '+version,audit.get('passed') is True and audit.get('failed_checks')==0 and audit.get('complete_replayed_cases')==19)
        e.require('historical result complete '+version,result.get('complete_cases')==19 and [x['case'] for x in result['periods']]==NAMES)
        for filename in ('plan.json','results.json'):
            e.require('historical audit binding '+version+'/'+filename,audit.get('hashes',{}).get(filename)==sha(folder/filename))
        required=['plan.json','results.json','audit.json']+[name+'/predictions.csv.gz' for name in NAMES]
        if version in ('v8','v14'):
            required += [name+'/'+file for name in NAMES for file in ('calibration_scores.csv.gz','freeze.json','bundle.joblib')]
        for file in required:
            e.require('historical input pinned '+version+'/'+file,str((folder/file).relative_to(ROOT)) in plan['input_sha256'])
        for name in NAMES:
            audited_files=('predictions.csv.gz','calibration_scores.csv.gz','freeze.json','bundle.joblib') if version in ('v8','v14') else ('predictions.csv.gz',)
            for file in audited_files:
                e.require('historical artifact audit hash '+version+'/'+name+'/'+file,
                    audit.get('hashes',{}).get(name+'/'+file)==plan['input_sha256'][str((folder/name/file).relative_to(ROOT))])
        inherited[version]={'audit_sha256':sha(folder/'audit.json'),'results_sha256':sha(folder/'results.json'),
            'passed':True,'scope':'Inherited completed audit; no new sensor or model execution by V15 auditor.'}
    e.tree('declared inherited model binding',plan['inherited_model_audit'],
        {v:{k:inherited[v][k] for k in ('audit_sha256','results_sha256')} for v in ('v8','v14')})
    return plan,inherited


def validate_frozen(run,e):
    frozen=read(run/'policies-frozen.json')
    e.tree('all policies frozen before tests',frozen,{'all19_calibration_complete':True,
        'outer_test_numeric_values_opened':False,'plan_sha256':sha(run/'plan.json')})
    e.require('exact frozen policy identities',list(frozen['policies'])==NAMES)
    for name,item in frozen['policies'].items():
        for file,key in [('selection.json','selection_sha256'),('trials.json','trials_sha256'),('calibration_predictions.csv.gz','calibration_predictions_sha256')]:
            e.require('frozen output '+name+'/'+file,sha(run/name/file)==item[key])
        selection=read(run/name/'selection.json');e.tree('frozen selection '+name,selection,{'choice':item['choice'],'accepted':item['accepted']})
    return frozen


def csv(path,numeric_files):
    numeric_files.append(str(path.relative_to(ROOT)))
    return pd.read_csv(path,float_precision='round_trip')


def load_calibration(name,e,numeric_files):
    v14=parent('v14')/name;v8=parent('v8')/name
    freeze=read(v14/'freeze.json');other=read(v8/'freeze.json')
    e.tree(name+' calibration geometry',other,{k:freeze[k] for k in ('calibration_starts','test')})
    a=csv(v14/'calibration_scores.csv.gz',numeric_files);b=csv(v8/'calibration_scores.csv.gz',numeric_files)
    for key in ('sample_index','label','reference'):e.array(name+' calibration common '+key,a[key],b[key])
    starts=freeze['calibration_starts'];end=freeze['test'][0]
    e.require(name+' four ordered blocks',len(starts)==4 and all(a<b for a,b in zip(starts,starts[1:]+[end])))
    e.array(name+' original calibration axis',a.sample_index,np.arange(starts[0],end))
    blocks=[]
    for i,(left,right) in enumerate(zip(starts,starts[1:]+[end])):
        l,r=left-starts[0],right-starts[0]
        blocks.append({'labels':a.label.iloc[l:r].to_numpy(np.int8),'v6':a.reference.iloc[l:r].to_numpy(np.int8),
            'v8':b.candidate.iloc[l:r].to_numpy(np.int8),'scores':a.long_context.iloc[l:r].to_numpy(float),
            'source_start':left,'block_id':str(i)})
    return blocks,a


def audit_calibration_case(run,name,frozen,e,numeric_files,full_grid):
    blocks,source=load_calibration(name,e,numeric_files);saved=read(run/name/'selection.json')
    if full_grid:
        selected,trials=oracle_calibrate(blocks)
        e.tree(name+' all independent early trials',read(run/name/'trials.json'),trials)
        e.tree(name+' independent early winner and veto',saved,selected)
        e.require(name+' compact search',1<=len(trials)<=64)
    else:
        e.tree(name+' frozen choice final assessment',saved['final_assessment'],evaluate(blocks,saved['choice'],False))
        if saved['proposed'] is not None:
            e.tree(name+' later fixed choice assessment',saved['later_certificate'],evaluate(blocks[2:],saved['proposed']))
            e.tree(name+' all4 fixed choice assessment',saved['all_four_veto'],evaluate(blocks,saved['proposed'],False))
    choices=frozen['policies'][name];e.tree(name+' policy choice',saved,{'choice':choices['choice'],'accepted':choices['accepted']})
    predicted=np.concatenate([scalar_components(b['v6'],b['v8'],b['scores'],saved['choice'])['final'] for b in blocks])
    actual=csv(run/name/'calibration_predictions.csv.gz',numeric_files)
    e.array(name+' cal replay axis',actual.sample_index,source.sample_index);e.array(name+' scalar cal output',actual.candidate,predicted)
    return {'rows':len(predicted),'accepted':saved['accepted'],'choice':saved['choice'],'proposed':saved['proposed'],
        'earlier_trials':saved['earlier_trial_count'],'feasible_earlier_trials':saved['feasible_earlier_trials'],
        'independent_early_search_replayed':full_grid,'scalar_final_replayed':True}


def audit_test_case(run,name,metadata,frozen,e,numeric_files):
    source=csv(parent('v14')/name/'predictions.csv.gz',numeric_files)
    history={v:(source if v=='v14' else csv(parent(v)/name/'predictions.csv.gz',numeric_files)) for v in HISTORY}
    for v,h in history.items():
        for key in ('sample_index','label','reference','baseline'): e.array(name+':'+v+':original axis '+key,h[key],source[key])
    frozen_geometry=read(parent('v14')/name/'freeze.json')['test']
    e.array(name+' fixed outer interval',source.sample_index,np.arange(*frozen_geometry))
    y=source.label.to_numpy(np.int8);v6=source.reference.to_numpy(np.int8);v8=history['v8'].candidate.to_numpy(np.int8)
    pred=scalar_components(v6,v8,source.long_context.to_numpy(),frozen['policies'][name]['choice'])['final']
    expected=pd.DataFrame({'sample_index':source.sample_index,'label':y,'baseline':source.baseline,'reference':v6,
        'v8':v8,'long_context':source.long_context,'candidate':pred})
    result={'case':name,'source':metadata[name]['source'],'accepted_calibration':frozen['policies'][name]['accepted'],
        'comparisons':comparisons(y,source.baseline.to_numpy(np.int8),v6,pred),'v8_comparison':pair(y,v8,pred),'history':{}}
    for v,h in history.items():
        expected['history__'+v]=h.candidate.to_numpy(np.int8);result['history'][v]=pair(y,h.candidate.to_numpy(np.int8),pred)
    saved=csv(run/name/'predictions.csv.gz',numeric_files)
    e.require(name+' exact prediction schema',list(saved.columns)==list(expected.columns))
    for key in expected: e.array(name+' frozen prediction '+key,saved[key],expected[key])
    e.tree(name+' saved full metrics',read(run/name/'results.json'),result)
    return result,expected


def aggregate(periods,by_source,e):
    sources={};v8_sources={};historical={}
    for source,frames in by_source.items():
        rows=pd.concat(frames,ignore_index=True);e.array(source+' contiguous pooled axis',np.diff(rows.sample_index),np.ones(len(rows)-1,np.int64))
        y=rows.label.to_numpy(np.int8);p=rows.candidate.to_numpy(np.int8)
        sources[source]=comparisons(y,rows.baseline.to_numpy(np.int8),rows.reference.to_numpy(np.int8),p)
        v8_sources[source]=pair(y,rows.v8.to_numpy(np.int8),p)
        historical[source]={v:pair(y,rows['history__'+v].to_numpy(np.int8),p) for v in HISTORY}
    summ=summary(periods,sources);all_v8=[p['v8_comparison'] for p in periods]+list(v8_sources.values())
    checks={'all_periods_and_source_pools_noninferior':all(p['noninferior'] for p in all_v8),
        'strictly_fewer_pooled_false_fragments':sum(p['candidate']['false_positive_runs'] for p in v8_sources.values())<sum(p['baseline']['false_positive_runs'] for p in v8_sources.values()),
        'false_fragment_reduction_in_two_periods':sum(p['v8_comparison']['candidate']['false_positive_runs']<p['v8_comparison']['baseline']['false_positive_runs'] for p in periods)>=2}
    retention={v:{'retained':all(not p['history'][v]['lost_baseline_event_ids'] for p in periods) and all(not p[v]['lost_baseline_event_ids'] for p in historical.values()),
        'lost':{p['case']:p['history'][v]['lost_baseline_event_ids'] for p in periods if p['history'][v]['lost_baseline_event_ids']},
        'lost_source_pools':{s:p[v]['lost_baseline_event_ids'] for s,p in historical.items() if p[v]['lost_baseline_event_ids']}} for v in HISTORY}
    quality=all(checks.values()) and all(p['retained'] for p in retention.values()) and summ['if_vs_v7']['passes_declared_development_gate'] and summ['v6_vs_v7']['passes_declared_development_gate']
    return {'periods':periods,'sources':sources,'summary':summ,'v8_sources':v8_sources,'v8_checks':checks,
        'historical_retention':retention,'historical_source_comparisons':historical,
        'v8_totals':{m:totals([p[m] for p in v8_sources.values()]) for m in ('baseline','candidate')},
        'quality_checks_before_independent_audit_passed':bool(quality)}


def execute(stage,run):
    run=Path(run).resolve();e=Evidence();numeric_files=[];hashes={};cases={};outer_complete=0
    report={'audit_version':AUDIT_VERSION,'stage':stage,'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'passed':False,'audit_script_sha256':sha(__file__),'development_only':True,'fresh_validation':False,
        'scope':'Independent scalar frozen-score policy replay plus inherited hash-bound sensor evidence. No model fit, raw-sensor reconstruction, streaming validation, hardware or app promotion.',
        'production_v15_predictor_or_checks_called':False,'original_axis_metric_provider':'ml.gecco_v6.unknown_label_metrics',
        'all_sources_previously_disclosed':True,'model_refitted':False,'raw_sensor_replay_performed':False}
    destination=run/('calibration-audit.json' if stage=='calibration' else 'audit.json')
    try:
        plan,inherited=verify_plan(run,e);frozen=validate_frozen(run,e)
        hashes.update({'plan.json':sha(run/'plan.json'),'policies-frozen.json':sha(run/'policies-frozen.json')})
        report.update(plan_sha256=hashes['plan.json'],policies_sha256=hashes['policies-frozen.json'],inherited_sensor_audits=inherited)
        if stage=='calibration':
            e.require('no test access before calibration audit',not (run/'test-started.json').exists())
        else:
            calibration=read(run/'calibration-audit.json');started=read(run/'test-started.json')
            e.tree('matching passed calibration audit',calibration,{'audit_version':AUDIT_VERSION,'stage':'calibration','passed':True,
                'complete_replayed_cases':19,'failed_checks':0,'audit_script_sha256':sha(__file__),
                'plan_sha256':hashes['plan.json'],'policies_sha256':hashes['policies-frozen.json']})
            e.tree('test started only after audit',started,{'policies_sha256':hashes['policies-frozen.json'],
                'calibration_audit_sha256':sha(run/'calibration-audit.json'),'one_fixed_outer_pass':True})
            hashes['calibration-audit.json']=sha(run/'calibration-audit.json');hashes['test-started.json']=sha(run/'test-started.json')
        for name in NAMES:
            cases[name]=audit_calibration_case(run,name,frozen,e,numeric_files,stage=='calibration')
            for f in ('selection.json','trials.json','calibration_predictions.csv.gz'): hashes[name+'/'+f]=sha(run/name/f)
            print(json.dumps({'audit':stage,'phase':'calibration','case':name,'passed':True}),flush=True)
        report['calibration_rows_replayed']=sum(x['rows'] for x in cases.values());report['calibration_by_case']=cases
        if stage=='test':
            completed=read(run/'results.json');metadata={p['case']:p for p in read(parent('v14')/'results.json')['periods']}
            e.tree('complete test result scope',completed,{'candidate_version':'V15','complete_cases':19,'expected_cases':19,
                'all_prespecified_cases_complete':True,'development_only':True,'fresh_validation':False,'no_model_fit':True,
                'inherited_sensor_audit_not_new_raw_replay':True,'no_promotion':True,
                'current_quality_goal_passed':False,'independent_test_audit_pending':True,
                'accepted_calibration_cases':sum(p['accepted'] for p in frozen['policies'].values())})
            e.tree('test case order',[p['case'] for p in completed['periods']],NAMES)
            periods=[];by_source={};test_rows=0
            for name in NAMES:
                period,rows=audit_test_case(run,name,metadata,frozen,e,numeric_files)
                periods.append(period);by_source.setdefault(period['source'],[]).append(rows);test_rows+=len(rows)
                outer_complete+=1;report['replayed_rows']=test_rows
                for f in ('predictions.csv.gz','results.json'): hashes[name+'/'+f]=sha(run/name/f)
                print(json.dumps({'audit':'test','phase':'outer','case':name,'rows':len(rows),'passed':True}),flush=True)
            result=aggregate(periods,by_source,e);e.tree('independent full results and objectives',completed,result)
            hashes['results.json']=sha(run/'results.json');report['replayed_rows']=test_rows
            report['independent_quality_checks_passed']=result['quality_checks_before_independent_audit_passed']
            report['summary']=result['summary'];report['v8_checks']=result['v8_checks'];report['historical_retention']=result['historical_retention']
        verify_plan(run,e);validate_frozen(run,e)
        report['complete_replayed_cases']=len(cases) if stage=='calibration' else outer_complete
        e.require('all19 completed',report['complete_replayed_cases']==19)
        report['passed']=True;report['failed_checks']=0
    except Exception as error:
        report['failed_checks']=1;report['error']=type(error).__name__+': '+str(error)
        report['complete_replayed_cases']=len(cases) if stage=='calibration' else outer_complete
    report.update(complete_replayed_calibration_cases=len(cases),total_checks=e.checks,total_numeric_checks=e.numeric,hashes=hashes,numeric_files_read=numeric_files)
    destination.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:report.get(k) for k in ('stage','passed','complete_replayed_cases','failed_checks','total_numeric_checks','error')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['calibration','test']);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();raise SystemExit(execute(args.stage,args.output))
