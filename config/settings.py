"""Small local configuration; production requires an explicit private secret."""
import os
import secrets
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DEBUG = os.getenv("DJANGO_DEBUG", "true").lower() == "true"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY and DEBUG:
    # Persist a private development secret so cookies survive restarts.
    local = BASE_DIR / ".local"
    local.mkdir(exist_ok=True, mode=0o700)
    secret_file = local / "django-secret"
    try:
        with secret_file.open("x") as stream:
            secret_file.chmod(0o600)
            stream.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
    SECRET_KEY = secret_file.read_text().strip()
if not SECRET_KEY:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY in your private .env before hosting.")
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
                  "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "lab"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
              "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
              "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
              "django.middleware.clickjacking.XFrameOptionsMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True,
              "OPTIONS": {"context_processors": ["django.template.context_processors.request",
                         "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3",
                         "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE"},
                         "TEST": {"NAME": BASE_DIR / "test.sqlite3"}}}
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"
GUEST_USERNAME = "guest"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 3600 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
# Opt in ONLY when Gunicorn is loopback-only behind your own HTTPS proxy.
if os.getenv('DJANGO_TRUST_PROXY','false').lower()=='true':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO','https')
CSRF_TRUSTED_ORIGINS = [v.strip() for v in os.getenv('DJANGO_CSRF_TRUSTED_ORIGINS','').split(',') if v.strip()]
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = int(os.getenv("LAB_MAX_REQUEST_BYTES", "12000000"))
LAB_MAX_VARIABLE_ENTRIES = int(os.getenv("LAB_MAX_VARIABLE_ENTRIES", "5000"))
LAB_MAX_PARAMETER_ENTRIES = int(os.getenv("LAB_MAX_PARAMETER_ENTRIES", "500000"))
LAB_MAX_AST_NODES = int(os.getenv("LAB_MAX_AST_NODES", "500"))
LAB_SOLVE_SECONDS = float(os.getenv("LAB_SOLVE_SECONDS", "2"))
LAB_MAX_CRITERIA = int(os.getenv('LAB_MAX_CRITERIA', '8'))
LAB_MAX_FRONTIER_SAMPLES = int(os.getenv('LAB_MAX_FRONTIER_SAMPLES', '50'))
LAB_FRONTIER_SECONDS = float(os.getenv('LAB_FRONTIER_SECONDS', '20'))
LAB_MAX_ASSETS = int(os.getenv('LAB_MAX_ASSETS', '100'))
LAB_MAX_PRICE_ROWS = int(os.getenv('LAB_MAX_PRICE_ROWS', '5000'))
LAB_FETCH_SECONDS = float(os.getenv('LAB_FETCH_SECONDS', '60'))
LAB_CACHE_HOURS = float(os.getenv('LAB_CACHE_HOURS', '24'))
LAB_EVALUATION_SECONDS = float(os.getenv('LAB_EVALUATION_SECONDS', '45'))
LAB_MAX_REFITS = int(os.getenv('LAB_MAX_REFITS', '300'))
