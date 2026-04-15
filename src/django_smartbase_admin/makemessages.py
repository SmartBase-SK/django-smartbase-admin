#!/usr/bin/env python

import django

from django.conf import settings
from django.core.management import call_command

settings.configure(
    DEBUG=True,
    LANGUAGES=[
        ("sk", "Slovak"),
        ("en", "English"),
        ("de", "German"),
        ("cs", "Czech"),
        ("hu", "Hungarian"),
        ("ro", "Romanian"),
        ("sl", "Slovenian"),
        ("hr", "Croatian"),
        ("fr", "French"),
        ("pl", "Polish"),
        ("it", "Italian"),
    ],
    USE_I18N=True,
    USE_L10N=True,
    USE_TZ=True,
    LOCALE_PATHS=("locale/",),
)

django.setup()

for lang_code, _ in settings.LANGUAGES:
    call_command("makemessages", "-l", lang_code, "--no-location", "--no-wrap")
