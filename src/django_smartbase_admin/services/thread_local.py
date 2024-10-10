from contextvars import ContextVar

sb_admin_request = ContextVar("sb_admin_request")


class SBAdminThreadLocalService:
    @classmethod
    def get_request(cls):
        return sb_admin_request.get()

    @classmethod
    def set_request(cls, request):
        sb_admin_request.set(request)
