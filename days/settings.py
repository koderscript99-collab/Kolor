from decouple import config
from pathlib import Path
import dj_database_url
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# =========================
# SECURITY
# =========================
SECRET_KEY = config("SECRET_KEY", default="fallback-dev-key-change-in-production")
FLW_SECRET_KEY     = config("FLW_SECRET_KEY")
FLW_WEBHOOK_SECRET = config("FLW_WEBHOOK_SECRET", default="")

# Debug: True locally, False on Render
DEBUG = config("DEBUG", default="True") == "True"

ALLOWED_HOSTS = [
    "kolor-1.onrender.com",
    "127.0.0.1",
    "localhost",
    "celibate-cheesy-eatable.ngrok-free.dev",
]

CSRF_TRUSTED_ORIGINS = [
    "https://kolor-1.onrender.com",
    "https://celibate-cheesy-eatable.ngrok-free.dev",
]

# =========================
# APPS
# =========================
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'mount',
    'rest_framework',
    'rest_framework.authtoken',
]

# =========================
# MIDDLEWARE
# =========================
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # ← must be right after SecurityMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'days.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'days.wsgi.application'

# =========================
# DATABASE
# =========================
# Uses DATABASE_URL env var on Render (PostgreSQL)
# Falls back to local PostgreSQL for development
DATABASE_URL = config("DATABASE_URL", default=None)

if DATABASE_URL:
    # Render / production — use DATABASE_URL
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    # Local development — use local PostgreSQL
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME":     "kolor_db",
            "USER":     "postgres",
            "PASSWORD": "00000000",
            "HOST":     "localhost",
            "PORT":     "5432",
        }
    }

# =========================
# PASSWORD VALIDATION
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =========================
# INTERNATIONALISATION
# =========================
LANGUAGE_CODE = "en-us"
TIME_ZONE     = "Africa/Lagos"  # ← changed to Nigerian timezone
USE_I18N = True
USE_TZ   = True

# =========================
# STATIC FILES
# =========================
STATIC_URL  = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# =========================
# MEDIA FILES
# =========================
MEDIA_URL  = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# =========================
# AUTH
# =========================
LOGIN_URL             = "login"
LOGIN_REDIRECT_URL    = "home"
LOGOUT_REDIRECT_URL   = "signup"

# =========================
# SESSIONS
# =========================
SESSION_ENGINE               = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE           = 1209600  # 2 weeks
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST   = True

# =========================
# REST FRAMEWORK
# =========================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
}

# =========================
# DEFAULT PRIMARY KEY
# =========================
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"