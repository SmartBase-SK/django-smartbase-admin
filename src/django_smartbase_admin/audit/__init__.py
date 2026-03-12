"""
Django Smartbase Admin Audit - Automatic audit logging for admin operations.

Usage:
    Add 'django_smartbase_admin.audit' to INSTALLED_APPS to enable.

    Example:
        INSTALLED_APPS = [
            ...
            'django_smartbase_admin.audit',
            ...
        ]

    Then run migrations:
        python manage.py migrate sb_admin_audit
"""
