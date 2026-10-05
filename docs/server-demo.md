# Small server demo

The files in `deploy/` are templates, not an installed deployment. Use one
Gunicorn process behind Caddy HTTPS, with SQLite and private environment settings.
Eight request threads share the five numerical slots and one yfinance lock.
Each guest browser has a separate workspace; the owner keeps one persistent
workspace. No queue, execution client, or trading account integration is added.

## Prepare your server checkout

Choose a Linux server with Python 3.13, uv, and Caddy installed. Copy/clone this
repository to `/srv/convex-lab`, owned by your ordinary service user. Change the
paths in the examples if you choose another location. In that directory:

```bash
uv sync --locked --no-dev
cp .env.example .env
chmod 600 .env
```

Edit `.env` privately. Set `DJANGO_DEBUG=false`,
`DJANGO_ALLOWED_HOSTS=YOUR_DOMAIN`, `DJANGO_TRUST_PROXY=true`, and
`DJANGO_CSRF_TRUSTED_ORIGINS=https://YOUR_DOMAIN`. Set both Alpaca environment
variables or an absolute `ALPACA_ENV_FILE` pointing to your existing private
credentials file; never include keys in commands, screenshots, or Git.

Generate a hosting secret directly into `.env`, without displaying it:

```bash
uv run python - <<'PY'
from pathlib import Path
import secrets
p = Path('.env')
lines = [line for line in p.read_text().splitlines() if not line.startswith('DJANGO_SECRET_KEY=')]
lines.append('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64))
p.write_text('\n'.join(lines) + '\n')
p.chmod(0o600)
PY
uv run python manage.py migrate
uv run python manage.py collectstatic --noinput
uv run python manage.py createsuperuser
uv run python manage.py create_guest
uv run python manage.py check --deploy
```

The guest password is in `.local/guest-login.txt`, readable only by the service
user. Share it privately with demo guests. It is not in the repository. Logout
ends a guest workspace; another login starts a new workspace. Two tabs in the
same browser login share a workspace intentionally. SQLite writes are short and
use WAL. Five guests were exercised in Chromium; large problems can still consume
CPU/memory. The math budgets are cooperative and compilation can exceed them.
Gunicorn's threaded timeout is a worker heartbeat, not a per-request kill switch.

## Run behind HTTPS

Replace `YOUR_USER` in `deploy/convex-lab.service`; replace `lab.example.com` in
`deploy/Caddyfile` with your domain. Point the domain at your server and permit
HTTP/HTTPS ports. Keep port 8020 loopback-only. Caddy replaces forwarded protocol
headers for HTTPS; only enable Django proxy trust with this controlled topology.

Copy the service to `/etc/systemd/system/convex-lab.service`, add the Caddy site
to your existing Caddy configuration, and validate it with `caddy validate`.
Do not replace other sites in an existing Caddyfile. Caddy must be able to read
`staticfiles/` and traverse its parent directories; it needs no access to `.env`,
`.local/`, or the database. Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now convex-lab
sudo systemctl reload caddy
```

Visit your HTTPS domain. Verify login, local KaTeX/Plotly assets, a small solve,
and two independent guest browser sessions. Back up the SQLite database using
SQLite's backup API (not a live filesystem copy without its WAL):

```bash
uv run python - <<'PY'
from pathlib import Path
import sqlite3
p = Path('.local/backup.sqlite3')
with sqlite3.connect('db.sqlite3') as source, sqlite3.connect(p) as target:
    source.backup(target)
p.chmod(0o600)
PY
```

That backup includes prices, results, and user records; keep it private.

## Daily data refresh after market close

The owner checks **Refresh daily after market close** when creating a dataset,
or changes this preference on its fetch-progress page. Guests cannot schedule.
Before installing a timer, try the bounded command:

```bash
uv run python manage.py refresh_datasets --owner YOUR_DJANGO_USERNAME --max-batches 20
```

Replace `YOUR_USER` and `YOUR_DJANGO_USERNAME` in
`deploy/convex-lab-refresh.service`. Copy it and the matching timer into
`/etc/systemd/system/`, then:

```bash
systemd-analyze calendar 'Mon..Fri *-*-* 22:30:00 UTC'
sudo systemctl daemon-reload
sudo systemctl enable --now convex-lab-refresh.timer
systemctl list-timers convex-lab-refresh.timer
```

The timer fires weekdays at 22:30 UTC (18:30 New York summer, 17:30 winter),
after the app's 17:00 completed-day cutoff. Holidays naturally return no new bars;
there is no exchange-calendar service. `Persistent=true` catches a missed run.
The command makes at most 200 batches for all watched universes; unfinished
batches stay saved and can resume in the browser or a subsequent command.
Previous provider errors get one fresh attempt per run, not an endless retry.
Existing experiments and their datasets remain immutable. A changed snapshot
gets a new fingerprint; overlapping refreshed holdouts are **not** statistically
independent final tests. Use fresh, genuinely unseen dates for a new final claim.

## Official configuration references

[Django deployment checklist](https://docs.djangoproject.com/en/6.1/howto/deployment/checklist/),
[Gunicorn settings](https://gunicorn.org/reference/settings/),
[Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[systemd timer source documentation](https://github.com/systemd/systemd/blob/main/man/systemd.timer.xml).
The old Gunicorn documentation URL returned 404; the current official site and
installed 26.2.0 settings were verified instead. No server services were installed
on the development laptop.

Verified locally: Django deployment checks reported no issues; Gunicorn 26.2.0
started on a temporary loopback port and served login HTML with forwarded HTTPS
and security headers; Caddy 2.11.7 validated the example configuration;
`systemd-analyze calendar` accepted the weekday UTC timer. These checks prepare
the configuration; actual domain certificates and server permissions must be
checked on your server. Temporary test processes were stopped.
