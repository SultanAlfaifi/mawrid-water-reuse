"""Exhaustive, preregistered extension to all52 untouched pond-phase cohorts.

The four primary M/Phase1 results are already disclosed. This is an extension
within the same experiment, not another independent source. The q50 method is
unchanged. No outcomes are printed until all312 planned periods complete.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import numpy as np
import pandas as pd
import ponds_frozen_evaluation as core
from ponds_reserved_data import read_reserved_cohorts
from sparse_evaluation import assess_sparse_series
from evaluation import gates
from provenance import declare_protocol, check_protocol, begin_first_access, sha256, now

ROOT=core.ROOT; HERE=Path(__file__).resolve().parent
GEOMETRY=ROOT/'output/ml/gecco-v5-source-search/ponds_reserved_geometry.json'

def method_configuration(records):
    config=core.configuration()
    for key in ('cohorts','filter','expected_grid_rows_per_cohort'):config.pop(key,None)
    config.update({'evaluation':'Untouched52 pond-phase extension of the completed primary benchmark',
        'cohorts':records,'selection_rule':'Every one of52 remaining Pond/Sonde/Treatment/Replicate/Phase groups in publisher identity metadata; none selected or removed by values, missingness, labels or performance.',
        'geometry':'Same k=4..9 expanding-decile local fit/cal/test geometry, applied to each actual phase grid length with its original absolute relative-time slots. No cross-phase or cross-pond pooling for fitting.',
        'primary_results_disclosed':{'cohorts':4,'periods':24,'events':1,'baseline_detected':1,'candidate_detected':1,'false_runs_each':65,'candidate_gates_activated':0,'primary_acceptance_passed':False},
        'prior_exposure':'Four M/Phase1 cohorts are disclosed and excluded. All52 remaining groups have only identity/time metadata exposed; sensor suffixes remained opaque. This q50 method and calibration defaults are unchanged from the primary run.',
        'outcome_policy':'Complete all312 periods before reading outer metrics. Preserve every period, including unqualified calibration and failures; no post-outcome method changes called fresh.',
        'primary_acceptance':'All312 periods preserve every baseline event identity and availability with no increase in false-run rate or normal alarm duration; strict pooled false-run reduction, original identities within each continuous pond-phase source. Require the unchanged evidence minima.',
        'scope':'All52 remaining pond-phase series from one ecological experiment,15-minute conductivity anomaly labels; no MAWRID field efficacy, water safety probability, five physical fault classes, or3D/Pi performance claim.',
        'independence':'Pond-phases share one ecological experiment, including repeated ponds across phases; do not treat312 periods as312 independent deployments or as a second independent source.'})
    return config

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    metadata=json.loads(GEOMETRY.read_text());records=metadata['reserved_cohorts']
    identities=[tuple(record['identity']) for record in records]
    if len(identities)!=52 or len(set(identities))!=52:raise ValueError('Exactly52 distinct reserved groups required')
    config=method_configuration(records)
    paths=core.code_paths()+[HERE/'ponds_reserved_evaluation.py',HERE/'ponds_reserved_data.py',GEOMETRY]
    protocol=declare_protocol(ROOT,out,config,paths,[core.ARCHIVE])
    for relative in protocol['code']:
        target=out/'source'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/relative,target)
    begin_first_access(ROOT,out)
    cohorts=read_reserved_cohorts(core.ARCHIVE,identities)
    if list(cohorts)!=identities:raise ValueError('Predeclared cohort order/identity differs')
    for record,identity in zip(records,identities):
        frame=cohorts[identity]
        if (len(frame)!=record['grid_rows'] or int(frame.slot.iloc[0])!=record['first_slot']
            or int(frame.slot.iloc[-1])!=record['last_slot'] or int(frame.row_observed.sum())!=record['original_rows']):
            raise ValueError(f'Metadata geometry differs for {identity}')
    periods=[];pooled=[];sources={};qualified=[];count=0
    for identity,frame in cohorts.items():
        pond,sonde,treatment,replicate,phase=identity
        # Case names carry phase to avoid collisions across repeated sondes.
        stream=(f'{pond}_P{phase}_{treatment}_R{replicate}',sonde)
        parts=[];local_periods=[]
        for k in range(4,10):
            # Reuse the byte-identical primary method; suppress its24-case
            # progress wording and replace it with the extension case count.
            with redirect_stdout(io.StringIO()):result,pred=core.run_case(out,stream,frame,k)
            result['cohort_identity']=list(identity)
            periods.append(result);local_periods.append(result);parts.append(pred)
            qualified.append(result['baseline_calibration_qualified']);count+=1
            print(json.dumps({'completed_periods':count,'planned_periods':312,'case':result['case'],
                'outer_metrics':'withheld until all312 complete'}),flush=True)
        combined=pd.concat(parts,ignore_index=True);bounds=np.r_[0,np.cumsum([len(p) for p in parts])].tolist()
        result=assess_sparse_series(combined.EVENT.to_numpy(bool),combined.baseline.to_numpy(np.int8),
            combined.candidate.to_numpy(np.int8),combined.slot.to_numpy(np.int64),bounds,core.CADENCE)
        result['cohort_identity']=list(identity)
        result['baseline_calibrations_qualified']=all(p['baseline_calibration_qualified'] for p in local_periods)
        sources['_'.join(stream)]=core.compact(result);pooled.append(result['pooled'])
    overall=gates(periods,pooled)
    evidence={'baseline_detected_events':overall['totals']['baseline']['confirmed_new_alarm_inside_events'],
        'eventful_cohorts':sum(p['baseline']['confirmed_new_alarm_inside_events']>0 for p in pooled),
        'eventful_periods':sum(p['baseline']['confirmed_new_alarm_inside_events']>0 for p in periods),
        'all_baseline_calibrations_qualified':all(qualified)}
    sufficient=(evidence['baseline_detected_events']>=5 and evidence['eventful_cohorts']>=2
        and evidence['eventful_periods']>=2 and all(qualified))
    strata={}
    for phase in sorted(set(key[-1] for key in identities)):
        selected_periods=[p for p in periods if p['cohort_identity'][-1]==phase]
        selected_sources=[s['pooled'] for s in sources.values() if s['cohort_identity'][-1]==phase]
        strata[f'phase_{phase}']=gates(selected_periods,selected_sources)
    result={'completed_at_utc':now(),'protocol_sha256':sha256(out/'protocol.json'),
        'completed_cases':count,'completed_cohorts':len(cohorts),'overall':overall,
        'evidence':evidence,'sufficient_evidence':sufficient,
        'primary_acceptance_passed':bool(overall['stable_joint_improvement'] and sufficient),
        'sources':sources,'periods':core.compact(periods),'strata':strata,
        'scope':config['scope'],'independence':config['independence'],
        'upstream_limitation':config['upstream_limitation']}
    check_protocol(ROOT,out);core.write(out/'results.json',result)
    print(json.dumps({'all312_completed':True,'overall':overall,'evidence':evidence,
        'primary_acceptance_passed':result['primary_acceptance_passed']}),flush=True)

if __name__=='__main__':main()
