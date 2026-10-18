"""Three strictly earlier teacher generations, then one decision-head fit.

All19 final bundles/choices freeze before any outer test arrays are opened.
No source duplication, live integration, threshold-family search or raw cleanup.
"""
from __future__ import annotations
import argparse
import gc
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import joblib
import numpy as np
import pandas as pd
from ml.gecco_v7 import development_v2 as prior
from ml.gecco_v15 import development as v15
from ml.gecco_v15.calibration import calibrate
from ml.gecco_v16 import teachers,decisions,model as model_module
from ml.gecco_v12.baseline_evidence import BaselineEvidenceHGBScorer

ROOT=Path(__file__).resolve().parents[2]
NAMES=v15.NAMES
PROTOCOL=ROOT/'output/ml/gecco-v16-design/protocol.json'
PROTOCOL_SHA='f4aa6376ad9586196ce8fdb2484cae9fb92b56bfba601e866da009013ff61b9a'
V15_AUDIT_SHA='0a297adf68575da23d6cea7d54b34500b36bd7b3e370a141b09e5a15c2eb8045'
RESERVE=1024**3
sha,now=prior.sha,prior.now
VERSION='v16_forward_teacher_decision_head'


def write(path,value):
    """Atomic completion metadata; an interrupted temp file is not a seal."""
    path=Path(path);payload=json.dumps(value,indent=2,allow_nan=False)+'\n'
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(payload);temporary.replace(path)


def training_open(out):
    if (out/'policies-frozen.json').exists() or (out/'test-started.json').exists():
        raise ValueError('Training is sealed; direct case entry cannot reopen it')


def geometry(n):
    if isinstance(n,bool) or not isinstance(n,(int,np.integer)) or n<16:
        raise ValueError('Original train length>=16 required')
    boundaries=[n*k//4 for k in range(1,5)]
    result=[]
    for i,(p,end) in enumerate(zip(boundaries[:-1],boundaries[1:]),1):
        fit_end=3*p//5
        cal_bounds=np.linspace(fit_end,p,5,dtype=np.int64).tolist()
        result.append({'fold':i,'fit':[0,fit_end],'calibration_bounds':cal_bounds,'forecast':[p,end]})
    return result


def guard(out):
    if shutil.disk_usage(out).free<RESERVE:
        raise RuntimeError('Disk reserve1GiB reached: preserve artifacts; run incomplete and resumable')


def verify(plan):
    for group in ('code_sha256','input_sha256'):
        for p,h in plan[group].items():
            if sha(ROOT/p)!=h:raise ValueError('Frozen bytes changed: '+p)


def prepare(out):
    if sha(PROTOCOL)!=PROTOCOL_SHA:raise ValueError('Protocol changed')
    if sha(v15.parent('v15')/'audit.json')!=V15_AUDIT_SHA:raise ValueError('Pinned V15audit changed')
    oldplan=json.loads((v15.parent('v15')/'plan.json').read_text())
    oldaudit=json.loads((v15.parent('v15')/'audit.json').read_text())
    if not oldaudit['passed'] or oldaudit['hashes']['plan.json']!=sha(v15.parent('v15')/'plan.json'):
        raise ValueError('V15lineage failure')
    for name in ['results.json']+[n+'/predictions.csv.gz' for n in NAMES]:
        if sha(v15.parent('v15')/name)!=oldaudit['hashes'][name]:
            raise ValueError('Pinned V15 audited artifact changed: '+name)
    v15.verify(oldplan)
    preflight_path=ROOT/'output/ml/gecco-v16-design/preflight.json'
    preflight=json.loads(preflight_path.read_text())
    if preflight.get('passed') is not True:raise ValueError('Complete synthetic preflight required')
    for p,h in preflight['code_sha256'].items():
        if sha(ROOT/p)!=h:raise ValueError('Code changed since preflight: '+p)
    out.mkdir(parents=True,exist_ok=False);guard(out)
    inputs={**oldplan['input_sha256']}
    paths=[PROTOCOL,preflight_path,ROOT/'output/ml/gecco-v16-design/preflight.log']
    for version in ('v8','v15'):
        folder=v15.parent(version)
        paths += [folder/n for n in ('plan.json','results.json','audit.json')]
    for name in NAMES:
        paths += [v15.parent('v15')/name/'predictions.csv.gz']
    original=json.loads((v15.parent('v14')/'plan.json').read_text())
    inputs.update(original['input_sha256'])
    for name,record in original['reference_sha256'].items():
        paths += [ROOT/record['folder']/n for n in ('bundle.joblib','freeze.json','calibration_scores.csv.gz','predictions.csv.gz')]
    inputs.update({str(p.relative_to(ROOT)):sha(p) for p in paths})
    for p,h in inputs.items():
        if sha(ROOT/p)!=h:raise ValueError('Inherited input changed:'+p)
    code={**oldplan['code_sha256'],**{str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'ml/gecco_v16').glob('*.py')}}
    audit_folder=ROOT/'ml/gecco_v16_audits'
    code.update({str(p.relative_to(ROOT)):sha(p) for p in audit_folder.glob('*.py')})
    for dependency in (ROOT/'ml').glob('gecco*_audits'):
        code.update({str(p.relative_to(ROOT)):sha(p) for p in dependency.glob('*.py')})
    plan={'created_at_utc':now(),'version':VERSION,'attempt':'v16_run01_forward_teacher_head',
        'development_only':True,'fresh_validation':False,'expected_cases':19,'case_order':NAMES,
        'code_sha256':code,'input_sha256':inputs,'protocol_sha256':PROTOCOL_SHA,
        'all_sources_previously_disclosed':True,'original_v15_audit_sha256':V15_AUDIT_SHA,
        'policy_family':'Exact frozen V15','all19_before_outer_test':True,'no_promotion':True,
        'source_axes':['2017','2018','2019','WaterHub']}
    write(out/'plan.json',plan)
    for p,h in code.items():
        dest=out/'source'/p;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/p,dest)
        assert sha(dest)==h
    print(json.dumps({'prepared':True,'code_files':len(code),'input_files':len(inputs),'plan_sha256':sha(out/'plan.json')}),flush=True)


def save_frame(path,frame):frame.to_csv(path,index=False)


def seal_inner(inner,record):
    write(inner/'complete.json',{'record':record,'files':{p.name:sha(p) for p in inner.iterdir() if p.is_file()}})


def run_case(case,out,plan,resume=False):
    training_open(out);guard(out);verify(plan);folder=out/case['name'];folder.mkdir(exist_ok=resume)
    started=time.perf_counter();x=case['train'].loc[:,case['channels']];y=case['train'][case['target']].to_numpy(np.int8)
    parent=v15.parent('v8')/case['name'];oldfreeze=json.loads((parent/'freeze.json').read_text())
    assert oldfreeze['train']==[0,len(x)] and oldfreeze['test']==[case['test_start'],case['test_end']]
    reference=joblib.load(parent/'bundle.joblib')
    original_if=reference['reference_bundle']['prior_bundle']['model'].baseline_
    n=len(x);fold_ids=np.full(n,-1,np.int8);available=np.zeros(n,bool)
    anchors=np.full(n,-1,np.int64);recoveries=np.full(n,-1,np.int64)
    matrices=[];indices=[];fold_records=[]
    for geom in geometry(n):
        guard(out);inner=folder/f"inner_{geom['fold']}"
        a=geom['fit'][1];bounds=geom['calibration_bounds'];p,end=geom['forecast']
        if resume and (inner/'complete.json').exists():
            sealed=json.loads((inner/'complete.json').read_text())
            for name,h in sealed['files'].items():assert sha(inner/name)==h
            record=sealed['record'];assert record['geometry']==geom
            if record['supported']:
                old=pd.read_csv(inner/'forecast.csv.gz',float_precision='round_trip')
                np.testing.assert_array_equal(old.sample_index,np.arange(p,end))
                np.testing.assert_array_equal(old.label,y[p:end])
                fold_ids[p:end]=geom['fold'];available[p:end]=old.base_available.to_numpy(bool)
                anchors[p:end]=old.anchor_origins.to_numpy(np.int64)
                recoveries[p:end]=old.recovery_origins.to_numpy(np.int64)
                with np.load(inner/'examples.npz',allow_pickle=False) as arrays:
                    matrices.append(arrays['matrix'].copy());indices.append(arrays['indices'].copy())
            fold_records.append(record)
            print(json.dumps({'case':case['name'],'phase':'resume_sealed_inner_fold','fold':geom['fold']}),flush=True)
            continue
        if inner.exists():
            if not resume:raise ValueError('Existing unsealed inner directory')
            # An interrupted, unsealed fit is never used as evidence. Preserve
            # its bytes, then repeat exactly the same prespecified fit.
            dest=folder/(inner.name+'_unsealed_'+str(time.time_ns()))
            inner.rename(dest)
            write(folder/('resume_'+str(time.time_ns())+'.json'),{'preserved_unsealed':dest.name,
                'repeat_same_geometry':geom,'reason':'Interrupted unsealed fit; no parameter/threshold selection from outcomes.'})
        inner.mkdir()
        print(json.dumps({'case':case['name'],'phase':'fit_past_teacher','fold':geom['fold'],'fit_end':a,'max_selection_index':p-1}),flush=True)
        teacher=teachers.fit_teacher(x.iloc[:a],y[:a],
            [x.iloc[l:r] for l,r in zip(bounds[:-1],bounds[1:])],
            [y[l:r] for l,r in zip(bounds[:-1],bounds[1:])],bounds[:-1],channels=case['channels'])
        metadata=teacher['training_metadata'];write(inner/'teacher_metadata.json',metadata)
        for k,frame in enumerate(teacher.get('calibration_data',[])):
            save_frame(inner/f'calibration_{k}.csv.gz',frame)
        write(inner/'calibration_trials.json',teacher.get('trials',{}))
        # Keep only fitted objects/lineage in joblib; numeric calibration files
        # and trials remain separate inspectable immutable outputs.
        saved={k:v for k,v in teacher.items() if k not in ('calibration_data','trials')}
        joblib.dump(saved,inner/'teacher.joblib',compress=3)
        del teacher
        if not saved['supported']:
            write(inner/'freeze.json',{'frozen_at_utc':now(),'geometry':geom,'supported':False,
                'teacher_sha256':sha(inner/'teacher.joblib'),'status':saved['status'],
                'max_fit_index':a-1,'max_selection_index':p-1,'no_forecast_prediction_invented':True})
            record={'geometry':geom,'supported':False,'status':saved['status']}
            fold_records.append(record);seal_inner(inner,record)
            del saved;gc.collect();continue
        inner_if=saved['v6_bundle']['prior_bundle']['model'].baseline_
        generator=model_module.fit_generator(case['channels'],inner_if,x.iloc[:a],y[:a])
        joblib.dump(generator,inner/'generator.joblib',compress=3)
        write(inner/'freeze.json',{'frozen_at_utc':now(),'geometry':geom,'supported':True,
            'teacher_sha256':sha(inner/'teacher.joblib'),'generator_sha256':sha(inner/'generator.joblib'),
            'max_fit_index':a-1,'max_selection_index':p-1,'first_forecast_index':p,
            'no_outer_calibration_or_test_used':True})
        # Forecast only after fitted teacher and feature generator are frozen.
        saved=joblib.load(inner/'teacher.joblib');generator=joblib.load(inner/'generator.joblib')
        forecast=teachers.predict_teacher(saved,x.iloc[p:end],gap_samples=120)
        v6,v8=(forecast[c].to_numpy(np.int8) for c in ('v6','v8'))
        matrix,ok,context=model_module.decision_matrix(generator,x.iloc[p:end],v6,v8,gap_samples=120)
        fold_ids[p:end]=geom['fold'];available[p:end]=ok
        for dest,key in ((anchors,'anchor_origins'),(recoveries,'recovery_origins')):
            values=context[key];dest[p:end]=np.where(values>=0,values+p,-1)
        keep=ok&context['active']&(y[p:end]>=0)
        matrices.append(matrix[keep]);indices.append(np.flatnonzero(keep)+p)
        forecast.insert(0,'sample_index',np.arange(p,end));forecast['label']=y[p:end]
        forecast['base_available']=ok
        for k in ('anchor_origins','recovery_origins'):forecast[k]=np.where(context[k]>=0,context[k]+p,-1)
        for k,name in enumerate(model_module.CONTEXT_NAMES):forecast[name]=context['matrix'][:,k]
        save_frame(inner/'forecast.csv.gz',forecast)
        np.savez_compressed(inner/'examples.npz',matrix=matrix[keep],indices=np.flatnonzero(keep)+p)
        record={'geometry':geom,'supported':True,'example_rows':int(keep.sum()),
            'teacher_sha256':sha(inner/'teacher.joblib'),'generator_sha256':sha(inner/'generator.joblib'),
            'forecast_sha256':sha(inner/'forecast.csv.gz'),'examples_sha256':sha(inner/'examples.npz')}
        fold_records.append(record);seal_inner(inner,record)
        del saved,generator,forecast,matrix,context;gc.collect()
    weights=decisions.weights(y,available,fold_ids,anchors,recoveries)
    all_indices=np.concatenate(indices) if indices else np.empty(0,np.int64)
    expected=np.flatnonzero(weights['eligible']);np.testing.assert_array_equal(all_indices,expected)
    width=len(BaselineEvidenceHGBScorer(case['channels'],original_if).feature_names_)+8
    example_matrix=np.concatenate(matrices) if matrices else np.empty((0,width),np.float32)
    examples={'matrix':example_matrix,'indices':expected,'fold_ids':fold_ids[expected],
        'event_ids':weights['event_ids'][expected],'weights':weights['sample'][expected],'summary':weights['summary']}
    np.savez_compressed(folder/'head_examples.npz',**{k:v for k,v in examples.items() if k!='summary'})
    save_frame(folder/'training_axis.csv.gz',pd.DataFrame({'sample_index':np.arange(n),'label':y,
        'fold_id':fold_ids,'base_available':available,'anchor_origins':anchors,'recovery_origins':recoveries,
        'eligible':weights['eligible'],'event_id':weights['event_ids'],
        'normalized_weight':weights['normalized'],'sample_weight':weights['sample']}))
    write(folder/'training_weights.json',{'summary':weights['summary'],'records':weights['records']})
    write(folder/'inner_lineage.json',{'folds':fold_records,'original_train':[0,n],
        'no_original_expert_thresholds_in_training':True})
    print(json.dumps({'case':case['name'],'phase':'fit_single_decision_head','examples':len(expected)}),flush=True)
    model=model_module.DecisionHeadScorer(case['channels'],original_if).fit_final(x,y,examples)
    write(folder/'model_inspection.json',model.inspection())
    del matrices,indices,examples,example_matrix,weights;gc.collect()
    # Exact frozen original V6/V8 calibration decisions, aligned to raw pastcal.
    cal=pd.read_csv(parent/'calibration_scores.csv.gz',float_precision='round_trip')
    labels=np.concatenate([part[case['target']].to_numpy(np.int8) for part in case['cal']])
    np.testing.assert_array_equal(cal.label,labels)
    np.testing.assert_array_equal(cal.sample_index,np.arange(case['cal_starts'][0],case['test_start']))
    edges=np.r_[0,np.cumsum([len(part) for part in case['cal']])]
    if case['continuous_cal']:
        base_matrix,base_ok=model_module.features_gap(model.generator_,pd.concat(case['cal'],ignore_index=True),gap_samples=120)
    blocks=[];cal_parts=[]
    for i,(l,r) in enumerate(zip(edges[:-1],edges[1:])):
        rows=cal.iloc[l:r];v6=rows.reference.to_numpy(np.int8);v8=rows.candidate.to_numpy(np.int8)
        if case['continuous_cal']:scores=model.score_matrix(base_matrix[l:r],base_ok[l:r],v6,v8)
        else:scores=model.score(case['cal'][i],v6,v8,gap_samples=120)
        blocks.append({'labels':labels[l:r],'v6':v6,'v8':v8,'scores':scores,
            'source_start':int(case['cal_starts'][i]),'block_id':str(i)})
        cal_parts.append(pd.DataFrame({'sample_index':rows.sample_index,'label':labels[l:r],
            'baseline':rows.baseline,'reference':v6,'v8':v8,'long_context':scores}))
    selected,trials=calibrate(blocks)
    from ml.gecco_v15.runtime import predict
    for rows,b in zip(cal_parts,blocks):rows['candidate']=predict(b['v6'],b['v8'],b['scores'],selected['choice'])
    save_frame(folder/'calibration_scores.csv.gz',pd.concat(cal_parts,ignore_index=True))
    write(folder/'selection.json',selected);write(folder/'trials.json',trials)
    bundle={'version':VERSION,'model':model,'reference_bundle':reference,'selected':selected,
        'sample_seconds':60,'gap_samples':120,'max_fit_index':n-1,'max_calibration_index':case['test_start']-1}
    joblib.dump(bundle,folder/'bundle.joblib',compress=3)
    verify(plan)
    artifacts={str(p.relative_to(folder)):sha(p) for p in folder.rglob('*') if p.is_file()}
    write(folder/'freeze.json',{'frozen_at_utc':now(),'case':case['name'],'source':case['source'],
        'plan_sha256':sha(out/'plan.json'),'train':[0,n],'calibration_starts':case['cal_starts'],
        'continuous_cal':case['continuous_cal'],'test':[case['test_start'],case['test_end']],
        'bundle_sha256':sha(folder/'bundle.joblib'),'selected':selected,'artifacts_sha256':artifacts,
        'outer_test_numerical_arrays_opened':False,'seconds':time.perf_counter()-started})
    print(json.dumps({'case':case['name'],'phase':'frozen_before_outer_test','head_fit_status':model.fit_status_,
        'choice':selected['choice'],'accepted':selected['accepted'],'seconds':round(time.perf_counter()-started,2)}),flush=True)


def train(out,resume=False):
    plan=json.loads((out/'plan.json').read_text());verify(plan)
    if (out/'test-started.json').exists() or (out/'policies-frozen.json').exists():raise ValueError('Training already sealed or outertest started')
    policies={}
    for name in NAMES:
        try:
            guard(out);folder=out/name
            if resume and (folder/'freeze.json').exists():
                f=json.loads((folder/'freeze.json').read_text());assert f['plan_sha256']==sha(out/'plan.json')
                for p,h in f['artifacts_sha256'].items():assert sha(folder/p)==h
            else:
                if folder.exists() and not resume:raise ValueError('Unsealed partialcase preserved; use declared resume: '+name)
                argv=[sys.executable,'-B','-m','ml.gecco_v16.development','case','--output',str(out),'--case',name]
                if resume:argv.append('--resume')
                subprocess.run(argv,cwd=ROOT,check=True)
                f=json.loads((folder/'freeze.json').read_text())
        except Exception as error:
            write(out/'incomplete.json',{'at_utc':now(),'case':name,'complete_cases':list(policies),
                'error':repr(error),'plan_sha256':sha(out/'plan.json'),'resume_same_frozen_recipe':True})
            raise
        policies[name]={'freeze_sha256':sha(folder/'freeze.json'),'bundle_sha256':f['bundle_sha256'],
            'choice':f['selected']['choice'],'accepted':f['selected']['accepted']}
    verify(plan)
    write(out/'policies-frozen.json',{'frozen_at_utc':now(),'plan_sha256':sha(out/'plan.json'),
        'all19_calibration_complete':True,'outer_test_numerical_arrays_opened':False,'policies':policies})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','train','case']);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--case',choices=NAMES);parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    if args.stage=='prepare':prepare(out)
    elif args.stage=='train':train(out,args.resume)
    else:
        if args.case is None:raise ValueError('Case required')
        training_open(out);plan=json.loads((out/'plan.json').read_text());verify(plan)
        for case in prior.cases('all'):
            if case['name']==args.case:run_case(case,out,plan,args.resume);break
        else:raise ValueError('Missing planned original case')
