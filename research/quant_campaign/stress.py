"""Controlled scale/conditioning tests. Synthetic tests are not market evidence."""
from time import perf_counter
import json
import numpy as np
import cvxpy as cp
from scipy.optimize import minimize
import plotly.graph_objects as go
from sklearn.covariance import LedoitWolf
from core.research import ResearchResult


def run(context,params):
    rows=[];checks=[]
    sizes=params.get('sizes',[5,20,50,100,154,256,500,1000])
    for n in sizes:
        variance=np.linspace(.00005,.0005,n)
        known=(1/variance)/(1/variance).sum()
        for solver in ('CLARABEL','OSQP','SCS'):
            start=perf_counter()
            try:
                w=cp.Variable(n)
                constraints=[cp.sum(w)==1,w>=0]
                problem=cp.Problem(cp.Minimize(cp.sum(cp.multiply(variance,cp.square(w)))),constraints)
                problem.solve(solver=solver)
                residual=max(float(np.max(np.asarray(c.violation()))) for c in constraints)
                error=float(np.max(np.abs(w.value-known)))
                rows.append([n,solver,problem.status,perf_counter()-start,residual,error])
                if n==5 and solver=='CLARABEL':
                    scipy=minimize(lambda v: np.dot(variance*v,v),np.ones(n)/n,
                        jac=lambda v:2*variance*v,method='SLSQP',bounds=[(0,1)]*n,
                        constraints=[{'type':'eq','fun':lambda v:v.sum()-1,'jac':lambda v:np.ones(n)}],
                        options={'ftol':1e-12,'maxiter':1000})
                    checks.append(['SLSQP independent check',bool(scipy.success),float(np.max(np.abs(scipy.x-w.value)))])
            except Exception as error:
                rows.append([n,solver,type(error).__name__,perf_counter()-start,None,None])
    for n in (5,100,154,256):
        r=context.rng.normal(0,.01,(63,n))
        sample=np.atleast_2d(np.cov(r,rowvar=False))
        shrunk=LedoitWolf(store_precision=False).fit(r).covariance_
        checks += [[f'{n} assets / 63 returns · sample rank',True,int(np.linalg.matrix_rank(sample))],
                   [f'{n} assets / 63 returns · shrunk rank',True,int(np.linalg.matrix_rank(shrunk))]]
    (context.artifact_dir/'capacity.json').write_text(json.dumps({'rows':rows,'checks':checks},allow_nan=False))
    fig=go.Figure()
    for solver in ('CLARABEL','OSQP','SCS'):
        chosen=[r for r in rows if r[1]==solver]
        fig.add_trace(go.Scatter(x=[r[0] for r in chosen],y=[r[3] for r in chosen],name=solver,mode='lines+markers'))
    fig.update_layout(title='Synthetic diagonal QP capacity · one CPU thread',xaxis_title='Assets',yaxis_title='Seconds',template='plotly_white')
    return ResearchResult(metrics={'cases':{'value':len(rows),'unit':'count'},
        'largest_solved_assets':{'value':max(r[0] for r in rows if r[2]=='optimal'),'unit':'count'}},
        text='Synthetic diagonal quadratic programs isolate numerical scale. They do not measure dense covariance, live data fetching, or rolling backtests. Approximate solver statuses require residual checks, not blind acceptance.',
        tables=[{'title':'Known-answer solver capacity','columns':['Assets','Solver','Status','Seconds','Constraint residual','Max weight error'],'rows':rows},
                {'title':'Independent and conditioning checks','columns':['Check','Executed','Value'],'rows':checks}],
        charts=[{'figure':fig.to_plotly_json()}],artifacts=['capacity.json'])
