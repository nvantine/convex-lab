"""Save a human review through the same result SDK used by agent models."""
from core.research import ResearchResult


def run(context,params):
    return ResearchResult(metrics=params.get('metrics',{}),tables=params.get('tables',[]),
        charts=params.get('charts',[]),text=params.get('text',''),equations=params.get('equations',[]))
