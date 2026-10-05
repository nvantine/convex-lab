"""Exercise the private hosting configuration in fresh subprocesses."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import pytest


def environment(**extra):
    return {**os.environ,'DJANGO_DEBUG':'false','DJANGO_SECRET_KEY':secrets.token_urlsafe(64),
            'DJANGO_ALLOWED_HOSTS':'lab.example.test','DJANGO_TRUST_PROXY':'true',**extra}


def test_deployment_checks():
    result=subprocess.run([sys.executable,'manage.py','check','--deploy'],env=environment(),
        capture_output=True,text=True,timeout=20)
    assert result.returncode==0 and 'System check identified no issues' in result.stdout


def test_gunicorn_options_are_supported():
    result=subprocess.run([sys.executable,'-m','gunicorn','--check-config','--config',
                           'deploy/gunicorn.conf.py','config.wsgi:application'],
        env=environment(),capture_output=True,text=True,timeout=20)
    assert result.returncode==0


def test_private_files_are_ignored_and_only_historical_client_is_used():
    for path in ('.env','.local/guest-login.txt','db.sqlite3','staticfiles/lab/lab.js'):
        assert subprocess.run(['git','check-ignore','-q',path]).returncode==0
    sources='\n'.join(p.read_text() for root in ('core','lab') for p in Path(root).rglob('*.py'))
    assert 'TradingClient' not in sources and 'submit_order' not in sources
    assert 'get_all_positions' not in sources and 'get_account(' not in sources


def test_pure_modules_have_no_django_imports():
    for path in Path('core').glob('*.py'):
        source=path.read_text()
        assert 'from django' not in source and 'import django' not in source
