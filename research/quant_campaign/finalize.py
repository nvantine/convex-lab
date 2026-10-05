"""Freeze validation choices, then explicitly open each real final window once."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
os.environ.setdefault('OMP_NUM_THREADS','1')
import contextlib
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import numpy as np
import plotly.graph_objects as go
from run_campaign import OUT,cli,data,datasets,FAMILIES


def read_cli(args):
    from lab.cli import main
    stream=io.StringIO()
    with contextlib.redirect_stdout(stream): code=main(args)
    response=json.loads(stream.getvalue())
    if code: raise RuntimeError(response.get('error'))
    return response['data']


def universes():
    yield from ((str(n),ds) for n,ds in datasets())
    for key in ('long-window','new-listing'):
        record=json.loads((OUT/(key+'.json')).read_text())
        yield key,data(record)['dataset']['id']


def flag(args,name,default):
    return json.loads(args[args.index(name)+1]) if name in args else default


def freeze():
    target=OUT/'frozen-final.json'
    if target.exists(): raise RuntimeError('Final protocol is already frozen; do not overwrite it.')
    selections=[];rows=[]
    for key,ds in universes():
        metadata=read_cli(['datasets','show',ds]);best={}
        for prefix in ('validation','lookback','estimators','ridge-alpha','risk-aversion'):
            path=OUT/f'{prefix}-{key}.json'
            if not path.exists():continue
            record=json.loads(path.read_text());args=record['argv']
            base_params=flag(args,'--params',{});base_options=flag(args,'--options',{})
            result=data(record)['result']
            for run_id,status,seed,changes,score in result['tables'][0]['rows']:
                if status!='complete' or score is None:continue
                params=dict(base_params);options={'mode':'rolling','frequency':'monthly','lookback':126,**base_options}
                for address,value in changes.items():
                    group,name=address.split('.',1)
                    (params if group=='params' else options)[name]=value
                family=params.get('family')
                if family not in best or score>best[family]['score']:
                    best[family]={'label':family,'params':params,'options':options,
                                  'validation_run_id':run_id,'score':score}
        if set(best)!=set(FAMILIES): raise RuntimeError(f'Incomplete families for {key}')
        for family in FAMILIES:
            chosen=best[family];evidence=read_cli(['runs','show',chosen['validation_run_id']])
            path=evidence['result']['portfolio'];reference=evidence['result']['equal_weight']
            excess=np.asarray(path['returns'])-np.asarray(reference['returns'])
            rng=np.random.default_rng(42);length=len(excess);means=[]
            for _ in range(1000):
                starts=rng.integers(0,length,size=int(np.ceil(length/21)))
                indices=np.concatenate([(start+np.arange(21))%length for start in starts])[:length]
                means.append(float(excess[indices].mean()*252))
            interval=np.quantile(means,[.025,.975]).tolist()
            chosen['validation_metrics']=path['metrics']
            chosen['validation_excess_interval']=interval
            chosen['options']=path['settings']
            rows.append([key,family,path['metrics']['cagr'],path['metrics']['sharpe'],path['metrics']['max_drawdown'],
                chosen['options']['frequency'],chosen['options']['lookback'],interval])
        revision=data(cli('register-final-'+key,['strategies','register','research/quant_campaign',
            '--entry-point','batch.py:run','--interface','research','--name','Quant final · '+key+' · '+metadata['provenance']['provider']]))
        selections.append({'universe':key,'dataset':ds,'metadata':metadata,'revision':revision['id'],
            'candidates':[best[f] for f in FAMILIES]})
    payload={'frozen_at':datetime.now(timezone.utc).isoformat(),
        'protocol':'One candidate per family/universe, highest validation Sharpe among main schedules, lookbacks, estimator and specified alpha/gamma/cap sensitivity. Fixed costs 10bps. Cost/gross stress trials excluded from selection. No final retuning.',
        'selections':selections}
    target.write_text(json.dumps(payload,indent=2,allow_nan=False))
    digest=hashlib.sha256(target.read_bytes()).hexdigest();(OUT/'frozen-final.sha256').write_text(digest+'\n')
    print('FROZEN',digest,'universes',len(selections),'candidates',len(rows),flush=True)
    report={'text':payload['protocol']+'\nFreeze hash: '+digest+'\nExploring many variants on validation creates selection bias. The block intervals are descriptive and not multiplicity-adjusted.',
        'metrics':{'frozen_candidates':{'value':len(rows),'unit':'count'}},
        'tables':[{'title':'Frozen validation winners, all families','columns':['Universe','Family','CAGR','Sharpe','Drawdown','Schedule','Lookback','95% block excess interval'],'rows':rows}]}
    report_path=OUT/'freeze-report-params.json';report_path.write_text(json.dumps(report))
    revision=data(cli('register-freeze-report',['strategies','register','research/quant_campaign','--entry-point','report.py:run','--interface','research','--name','Quant campaign · frozen validation protocol']))
    cli('freeze-report',['research','run',revision['id'],'--params','@'+str(report_path)])


def final():
    path=OUT/'frozen-final.json';digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=(OUT/'frozen-final.sha256').read_text().strip():raise RuntimeError('Frozen protocol changed.')
    for selection in json.loads(path.read_text())['selections']:
        key=selection['universe'];params=OUT/f'final-params-{key}.json'
        params.write_text(json.dumps({'candidates':selection['candidates'],'freeze_sha256':digest}))
        cli('final-'+key,['research','run',selection['revision'],'--dataset',selection['dataset'],
            '--window','holdout','--confirm-holdout','--params','@'+str(params),'--seed','42','--timeout','1800'])


if __name__=='__main__':
    {'freeze':freeze,'final':final}[sys.argv[1]]()
