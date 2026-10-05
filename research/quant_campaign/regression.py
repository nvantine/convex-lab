"""Save real-checkout regression evidence with isolated test databases."""
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
import core
from core.research import ResearchResult


def run(context,params):
    checkout=Path(core.__file__).resolve().parents[1]
    output=context.artifact_dir
    env={**os.environ,'LAB_DATABASE_PATH':str(output/'unused.sqlite3'),
         'LAB_TEST_DATABASE_PATH':str(output/'isolated-test.sqlite3')}
    command=[sys.executable,'-m','pytest','-m','not browser','-q','--junit-xml',str(output/'regression.xml')]
    result=subprocess.run(command,cwd=checkout,env=env,capture_output=True,text=True,timeout=120)
    (output/'regression.log').write_text(result.stdout+'\n'+result.stderr)
    xml=ET.parse(output/'regression.xml').getroot()
    counts={name:sum(int(s.get(name,'0')) for s in xml.iter('testsuite'))
            for name in ('tests','failures','errors','skipped')}
    rows=[]
    for case in xml.iter('testcase'):
        failure=case.find('failure')
        if failure is not None:rows.append([case.get('classname'),case.get('name'),failure.get('message')])
    return ResearchResult(metrics={**{key:{'value':value,'unit':'count'} for key,value in counts.items()},
                                  'pytest_exit_code':{'value':result.returncode,'unit':'code'}},
        text='This script saved the application test outcome; script completion is not a passing suite. The actual owner CLI configuration was retained, with separate temporary databases. Inspect pytest_exit_code and failures, plus JUnit/log artifacts.',
        tables=[{'title':'Failed application tests','columns':['Module','Test','Message'],'rows':rows}],
        artifacts=['regression.xml','regression.log'])
