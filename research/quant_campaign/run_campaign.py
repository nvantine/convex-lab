"""Drive only public CLI commands; resume by stable invocation keys.

Operational output is ignored under .local/quant-campaign-20261005. This script
does not inspect final price rows. Final batches require a separate phase.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'.local/quant-campaign-20261005'
OUT.mkdir(parents=True,exist_ok=True)
BASE='SPY AGG QQQ GLD TLT IWM EFA EEM LQD HYG VNQ DBC XLE XLK XLV XLF XLI XLP XLU XLB'.split()
EXTRA='VTI VOO VEA VWO BND TIP SHY IEF VGIT VGSH BIL SHV IAU SLV USO UNG DBA XBI IBB SMH SOXX ITB XHB IYR REM KRE KBE XRT IGV IYT'.split()
STOCKS='AAPL MSFT NVDA AMZN GOOGL META AVGO TSLA COST NFLX AMD ADBE CSCO QCOM TXN AMAT INTC INTU ISRG BKNG ADP GILD MU MDLZ PEP SBUX AMGN REGN PANW SNPS CDNS MAR ORLY MELI ABNB PYPL LULU FTNT NXPI MRVL KLAC LRCX ADSK CHTR CMCSA TMUS VRTX BIIB MCHP WDAY JPM BAC WFC C GS MS BRK-B V MA AXP UNH JNJ PFE MRK ABBV ABT TMO DHR MDT BMY LLY CVS CI HUM ZTS PG KO WMT HD LOW TGT NKE DIS MCD CAT DE HON UPS FDX GE IBM ORCL CRM NOW ACN VZ T CVX XOM COP SLB EOG NEM FCX'.split()
UNIVERSE=BASE+EXTRA+STOCKS
FAMILIES=['equal','inverse_vol','min_variance','mean_variance','momentum','trend_cash','entropy','cvar','turnover','signed_momentum','neutral_reversion','ridge','risk_cap']


def cli(key,args,extra_env=None):
    path=OUT/(key+'.json')
    if path.exists(): return json.loads(path.read_text())
    env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1',**(extra_env or {})}
    command=[sys.executable,'-m','lab.cli','--idempotency-key','quant-20261005-'+key,*map(str,args)]
    started=datetime.now(timezone.utc).isoformat()
    result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True)
    try: response=json.loads(result.stdout)
    except ValueError: response={'ok':False,'error':{'message':'CLI returned no valid JSON','stdout':result.stdout[-2000:]}}
    record={'started':started,'argv':['uv','run','convex-lab',*command[3:]],'env':extra_env or {},
            'exit_code':result.returncode,'response':response,'stderr':result.stderr[-5000:]}
    path.write_text(json.dumps(record,indent=2))
    with (OUT/'events.jsonl').open('a') as stream: stream.write(json.dumps({'key':key,'exit_code':result.returncode,'started':started})+'\n')
    print(key,'exit='+str(result.returncode),flush=True)
    return record


def data(record): return record['response'].get('data',{})


def register():
    for entry,interface,key in [('strategies.py:target_weights','portfolio','policy'),('batch.py:run','research','holdout-batch'),('stress.py:run','research','capacity')]:
        cli('register-'+key,['strategies','register','research/quant_campaign','--entry-point',entry,'--interface',interface,'--name','Quant campaign · '+key])
    cli('registered-tests',['tests','run',data(cli('register-policy',[]))['id'],'--timeout','120','--pytest-args','["-q"]'])


def fetch():
    # Demonstrate normal limit before configuring a larger research universe.
    cli('default-limit-101',['datasets','fetch','--source','alpaca','--symbols',','.join(UNIVERSE[:101]),'--start','2021-10-01','--end','2026-10-02','--name','Default limit probe'])
    for n in (5,10,20,50,100,len(UNIVERSE)):
        cli('data-'+str(n),['datasets','fetch','--source','alpaca','--symbols',','.join(UNIVERSE[:n]),'--start','2021-10-01','--end','2026-10-02','--batch-size','5','--name',f'Quant campaign · {n} assets'],{'LAB_MAX_ASSETS':str(len(UNIVERSE))})


def datasets():
    for n in (5,10,20,50,100,len(UNIVERSE)):
        path=OUT/f'data-{n}.json'
        if path.exists():
            record=json.loads(path.read_text());dataset=data(record).get('dataset')
            alternative=OUT/f'yahoo-{n}.json'
            if not dataset and alternative.exists():
                dataset=data(json.loads(alternative.read_text())).get('dataset')
            if dataset: yield n,dataset['id']


def validate():
    revision=data(cli('register-policy',[]))['id']
    for n,dataset in datasets():
        # All families across all trading schedules, plus estimation sensitivity.
        grid={'params.family':FAMILIES,'options.frequency':['hold','monthly','weekly','daily']}
        cli(f'validation-{n}',['sweep',revision,'--dataset',dataset,'--grid',json.dumps(grid),'--seeds','[42]','--max-trials','60','--timeout','1800','--metric','sharpe','--options','{"lookback":126,"cost_bps":10,"borrow_rate":0.03,"financing_rate":0.05}'])
        grid={'params.family':['min_variance','mean_variance','signed_momentum','ridge','turnover'],'options.lookback':[21,63,252]}
        cli(f'lookback-{n}',['sweep',revision,'--dataset',dataset,'--grid',json.dumps(grid),'--max-trials','20','--timeout','600','--options','{"frequency":"monthly","cost_bps":10,"borrow_rate":0.03,"financing_rate":0.05}'])
    # Cost and gross/cap sensitivity on smaller and larger universes.
    available=list(datasets())
    for n,dataset in (available[:1]+available[-1:] if available else []):
        grid={'params.family':['momentum','signed_momentum','neutral_reversion','turnover'],'options.cost_bps':[0,10,50,100]}
        cli(f'costs-{n}',['sweep',revision,'--dataset',dataset,'--grid',json.dumps(grid),'--max-trials','20','--timeout','600','--options','{"frequency":"weekly","lookback":63,"borrow_rate":0.03,"financing_rate":0.05}'])
        grid={'params.gross':[1,1.6,3],'params.cap':[.01,.1,.4]}
        cli(f'signed-{n}',['sweep',revision,'--dataset',dataset,'--params','{"family":"signed_momentum"}','--grid',json.dumps(grid),'--max-trials','12','--timeout','600','--options','{"frequency":"monthly","lookback":63,"cost_bps":10,"borrow_rate":0.03,"financing_rate":0.05}'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['register','fetch','validate'])
    phase=parser.parse_args().phase
    {'register':register,'fetch':fetch,'validate':validate}[phase]()
