from contextvars import ContextVar

sb_admin_request: ContextVar = ContextVar("sb_admin_request", default=None)


class SBAdminThreadLocalService:
    @classmethod
    def get_request(cls):
        return sb_admin_request.get()

    @classmethod
    def set_request(cls, request):
        sb_admin_request.set(request)

    @classmethod
    def clear_request(cls, **kwargs):
        """Reset the per-request contextvar to ``None``.

        Wired to Django's ``request_finished`` signal in ``SBAdminConfig.ready``
        so any request that bound the contextvar (admin view dispatch, MCP
        tool, custom call site) is unbound when the response is returned.
        Callers that want a tighter-scoped bind should use a ``with``-block
        around their own ``set_request`` / ``clear_request`` pair.
        """
        sb_admin_request.set(None)
