#!/usr/bin/env python
"""
Run django-smartbase-admin tests standalone.

Usage:
    python runtests.py                                          # all tests
    python runtests.py django_smartbase_admin.audit.tests       # audit tests
    python runtests.py django_smartbase_admin.audit.tests.test_audit_integration.TestAdminCRUD
"""
import os
import sys

import django
from django.conf import settings
from django.test.utils import get_runner


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

    # Ensure src/ is on the path so django_smartbase_admin is importable
    src_dir = os.path.join(os.path.dirname(__file__), "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    # Ensure project root is on the path so tests.settings is importable
    root_dir = os.path.dirname(__file__)
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    django.setup()
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=2)
    test_labels = sys.argv[1:] or ["django_smartbase_admin.audit.tests"]
    failures = test_runner.run_tests(test_labels)
    sys.exit(bool(failures))


if __name__ == "__main__":
    main()
