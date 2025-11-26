from pathlib import Path
import os
from dotenv import load_dotenv

# Load .env
load_dotenv()

# -------------------------------
# Project Base
# -------------------------------
CURRENT_FILE = Path(__file__).resolve()
BASE_DIR = CURRENT_FILE.parent.parent.parent  # project root

# -------------------------------
# Security & Debug
# -------------------------------
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-default-key')
DEBUG = os.getenv('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')
PATH_AFTER_BASE_DIR=os.getenv('PATH_AFTER_BASE_DIR')


# -------------------------------
# Docker configerations from .env 
# -------------------------------

PREDICT_DOCKER_URL = os.getenv("PREDICT_DOCKER_URL", "")
JOB_DATA_DIR = os.getenv("JOB_DATA_DIR", "/data")
MAX_SMILES_LIMIT = int(os.getenv("MAX_SMILES_LIMIT", 1))
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "1") == "1"
DEBUG_LOG = os.getenv("DEBUG_LOG", "0") == "1"


# -------------------------------
# Static & Media Files
# -------------------------------
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_ROOT = BASE_DIR / PATH_AFTER_BASE_DIR
MEDIA_URL = '/media/'   # Use relative URL here


# -------------------------------
# Installed apps, middleware etc.
# -------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'core',
    'rest_framework',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

CORS_ALLOW_ALL_ORIGINS = True

ROOT_URLCONF = 'evo_backend.urls'

# -------------------------------
# Templates
# -------------------------------
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'evo_backend.wsgi.application'

# -------------------------------
# DRF & Rate Limiting (ADDED)
# -------------------------------
REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        # 'anon' covers all users since you have no login
        # Format examples: '100/day', '10/minute', '5/second'
        'anon': '60/minute', 
    }
}

# -------------------------------
# Caching (ADDED - Required for throttling)
# -------------------------------
# This uses local memory to store the request counts.
# If you restart the server, the rate limit counts reset.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

# -------------------------------
# Database
# -------------------------------
DATABASES = {
    'default': {
        'ENGINE': os.getenv('DB_ENGINE', 'django.db.backends.postgresql'),
        'NAME': os.getenv('DB_NAME', 'evolf_db'),
        'USER': os.getenv('DB_USER', 'postgres'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', 'localhost'),
        'PORT': os.getenv('DB_PORT', '5432'),
    }
}

# -------------------------------
# Password validation
# -------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# -------------------------------
# Internationalization
# -------------------------------
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# -------------------------------
# Elasticsearch (if needed)
# -------------------------------
ELASTICSEARCH_DSL = {
    'default': {
        'hosts': os.getenv('ELASTIC_HOST'),
    },
}