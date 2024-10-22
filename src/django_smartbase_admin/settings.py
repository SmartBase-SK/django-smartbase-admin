from django.conf import settings

SB_ADMIN_PATH = getattr(settings, "SB_ADMIN_PATH", "sb-admin/")
setattr(settings, "SB_ADMIN_PATH", SB_ADMIN_PATH)
