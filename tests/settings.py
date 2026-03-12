"""
Minimal Django settings for running django-smartbase-admin tests standalone.
Uses SQLite and the default auth.User — no external database or project required.

Usage:
    python runtests.py                              # all tests
    python runtests.py django_smartbase_admin.audit  # audit tests only
"""

SECRET_KEY = "test-secret-key-not-for-production"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "easy_thumbnails",
    "filer",
    "widget_tweaks",
    "ckeditor",
    "ckeditor_uploader",
    "nested_admin",
    "django_smartbase_admin",
    "django_smartbase_admin.audit",
]

# SBAdmin configuration — None disables autodiscovery (not needed for tests)
SB_ADMIN_CONFIGURATION = None

# CKEditor requires an upload path setting
CKEDITOR_UPLOAD_PATH = "/tmp/ckeditor/"

# Required for Django
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
USE_TZ = True

ROOT_URLCONF = "django_smartbase_admin.urls"

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
