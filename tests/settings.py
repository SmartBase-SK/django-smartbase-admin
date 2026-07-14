"""
Minimal Django settings for running django-smartbase-admin tests standalone.
Uses SQLite and the default auth.User — no external database or project required.

Usage:
    python runtests.py                              # all tests
    python runtests.py django_smartbase_admin.audit  # audit tests only
"""

SECRET_KEY = "test-secret-key-not-for-production"

import os

from django_smartbase_admin.mcp.instructions import SBADMIN_MCP_SERVER_INSTRUCTIONS

# Defaults to in-memory SQLite — no credentials in the repo, no service
# required for CI. To exercise Postgres-only paths (JSON ``__contains``,
# ArrayAgg, etc.) locally, point the env var at your own database:
#   export SBADMIN_TEST_DATABASE_URL="postgresql://user:pass@host:port/db"
from urllib.parse import urlparse

_db_url = os.environ.get("SBADMIN_TEST_DATABASE_URL", "sqlite://")
_parsed = urlparse(_db_url)
if _parsed.scheme.startswith("sqlite"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": _parsed.path.lstrip("/") or ":memory:",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _parsed.path.lstrip("/"),
            "USER": _parsed.username or "",
            "PASSWORD": _parsed.password or "",
            "HOST": _parsed.hostname or "",
            "PORT": str(_parsed.port or ""),
        }
    }

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.postgres",
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
    "django_smartbase_admin.messaging",
    "oauth2_provider",
    "rest_framework",
    "mcp_server",
    "django_smartbase_admin.mcp",
]

LOGIN_URL = "/login/"

OAUTH2_PROVIDER = {
    "SCOPES": {"sbadmin:write": "Read-write access to SBAdmin data via MCP"},
    "DEFAULT_SCOPES": ["sbadmin:write"],
    "PKCE_REQUIRED": True,
    "ACCESS_TOKEN_EXPIRE_SECONDS": 3600,
    "REFRESH_TOKEN_EXPIRE_SECONDS": 0,
    "ALLOWED_REDIRECT_URI_SCHEMES": ["http", "https"],
}

# django-mcp-server: enforce OAuth on the MCP endpoint via DRF auth class
# that reads DOT's AccessToken table.
DJANGO_MCP_AUTHENTICATION_CLASSES = [
    "oauth2_provider.contrib.rest_framework.OAuth2Authentication",
]
DJANGO_MCP_GLOBAL_SERVER_CONFIG = {
    "name": "sbadmin",
    "instructions": SBADMIN_MCP_SERVER_INSTRUCTIONS,
    "stateless": True,
}
# Keep this slashless: remote clients such as Claude canonicalize the resource
# to `/mcp` and do not replay protocol POSTs across Django's slash redirect.
DJANGO_MCP_ENDPOINT = "mcp"

ALLOWED_HOSTS = ["*"]
DEBUG = True

# SBAdmin configuration for MCP smoke tests; production projects must provide one.
SB_ADMIN_CONFIGURATION = "tests.sbadmin_config.EmptySBAdminConfiguration"

# CKEditor requires an upload path setting
CKEDITOR_UPLOAD_PATH = "/tmp/ckeditor/"

# Required for Django
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"
USE_TZ = True

ROOT_URLCONF = "tests.mcp_urls"

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
