#!/usr/bin/env python

import django

from django.conf import settings
from django.core.management import call_command

settings.configure(
    DEBUG=True,
    LANGUAGES=[
        ("sk", "Slovak"),
    ],
    USE_I18N=True,
    USE_L10N=True,
    USE_TZ=True,
    LOCALE_PATHS=("locale/",),
)

django.setup()

call_command("makemessages", "-l", "sk", "--no-location", "--no-wrap")
