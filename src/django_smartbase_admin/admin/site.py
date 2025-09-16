from collections.abc import Callable
from functools import update_wrapper
from typing import Any

from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.http import HttpRequest, HttpResponse
from django.urls import path, reverse_lazy, URLPattern, URLResolver
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.generic import TemplateView

from django_smartbase_admin.engine.admin_entrypoint_view import SBAdminEntrypointView
from django_smartbase_admin.engine.request import SBAdminViewRequestData
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.views.global_filter_view import GlobalFilterView


class SBAdminSite(admin.AdminSite):
    login_template = "sb_admin/authentification/login.html"
    logout_template = "sb_admin/authentification/logout.html"
    password_change_template = "sb_admin/authentification/password_change.html"
    password_change_done_template = (
        "sb_admin/authentification/password_change_done.html"
    )

    def initialize_admin_view(
        self, view_func: Callable[..., HttpResponse], request: HttpRequest, **kwargs
    ) -> None:
        request.current_app = "sb_admin"
        selected_view = None
        try:
            selected_view = view_func.__self__
            from django_smartbase_admin.admin.admin_base import SBAdminBaseView

            if not isinstance(selected_view, SBAdminBaseView):
                selected_view = None
        except Exception:
            pass
        request.sbadmin_selected_view = selected_view
        kwargs["view"] = selected_view.get_id() if selected_view else None
        SBAdminThreadLocalService.set_request(request)
        request_data = SBAdminViewRequestData.from_request_and_kwargs(request, **kwargs)
        if selected_view:
            # Initialize SBAdmin, ModelAdmin instances, class-based SBAdminEntrypointView are initialized with request_data
            selected_view.init_view_dynamic(
                request, request_data=request_data, **kwargs
            )

    def admin_view_response_wrapper(
        self, response: HttpResponse, request: HttpRequest, *args, **kwargs
    ) -> HttpResponse:
        from django_smartbase_admin.admin.admin_base import SBAdminThirdParty

        if isinstance(request.sbadmin_selected_view, SBAdminThirdParty):
            response = SBAdminViewService.replace_legacy_admin_access_in_response(
                response
            )
        return response

    def admin_view(
        self,
        view_func: Callable[..., HttpResponse],
        *,
        cacheable: bool = False,
        public: bool = False
    ) -> Callable[[HttpRequest, ...], HttpResponse]:
        def inner(request: HttpRequest, *args, **kwargs):
            self.initialize_admin_view(view_func, request, **kwargs)
            response = view_func(request, *args, **kwargs)
            return self.admin_view_response_wrapper(response, request, *args, **kwargs)

        if not public:
            return super().admin_view(update_wrapper(inner, view_func), cacheable)
        # standard Django admin behaviour, expect it skips staff/permission checks
        if not cacheable:
            inner = never_cache(inner)
        if not getattr(view_func, "csrf_exempt", False):
            inner = csrf_protect(inner)
        inner = login_not_required(inner)
        return update_wrapper(inner, view_func)

    def each_context(self, request: HttpRequest) -> dict[str, Any]:
        try:
            return request.sbadmin_selected_view.get_global_context(request)
        except Exception:
            return {}

    def get_urls(self) -> list[URLPattern | URLResolver]:
        from django.contrib.auth.views import (
            PasswordResetView,
            PasswordResetDoneView,
            PasswordResetConfirmView,
            PasswordResetCompleteView,
            PasswordChangeView,
            PasswordChangeDoneView,
        )
        from django_smartbase_admin.views.user_config_view import ColorSchemeView

        urls = [
            path("login/", self.admin_view(self.login, public=True), name="login"),
            path("logout/", self.admin_view(self.logout), name="logout"),
            path(
                "password_change/",
                self.admin_view(
                    PasswordChangeView.as_view(
                        template_name="sb_admin/authentification/password_change_form.html",
                        success_url=reverse_lazy("sb_admin:password_change_done"),
                    )
                ),
                name="password_change",
            ),
            path(
                "password_change/done/",
                self.admin_view(
                    PasswordChangeDoneView.as_view(
                        template_name="sb_admin/authentification/password_change_done.html",
                    )
                ),
                name="password_change_done",
            ),
            path(
                "password_reset/",
                PasswordResetView.as_view(
                    template_name="sb_admin/authentification/password_reset_form.html",
                    email_template_name="sb_admin/authentification/password_reset_email.html",
                    success_url=reverse_lazy("sb_admin:password_reset_done"),
                ),
                name="password_reset",
            ),
            path(
                "password_reset/done/",
                PasswordResetDoneView.as_view(
                    template_name="sb_admin/authentification/password_reset_done.html",
                ),
                name="password_reset_done",
            ),
            path(
                "reset/<uidb64>/<token>/",
                PasswordResetConfirmView.as_view(
                    template_name="sb_admin/authentification/password_reset_confirm.html",
                    success_url=reverse_lazy("sb_admin:password_reset_complete"),
                ),
                name="password_reset_confirm",
            ),
            path(
                "reset/done/",
                PasswordResetCompleteView.as_view(
                    template_name="sb_admin/authentification/password_reset_complete.html",
                ),
                name="password_reset_complete",
            ),
        ]
        if settings.DEBUG:
            urls.append(
                path(
                    "components",
                    TemplateView.as_view(
                        template_name="sb_admin/includes/components.html"
                    ),
                    name="components",
                )
            )
        urls.extend(
            [
                path(
                    "",
                    self.admin_view(SBAdminEntrypointView.as_view()),
                    name="sb_admin_base",
                ),
                path(
                    "global-filter",
                    self.admin_view(GlobalFilterView.as_view()),
                    name="global_filter",
                ),
                path(
                    "color-scheme",
                    self.admin_view(ColorSchemeView.as_view()),
                    name="color_scheme",
                ),
                path(
                    "<str:view>/<str:action>/<str:modifier>",
                    self.admin_view(SBAdminEntrypointView.as_view()),
                    name="sb_admin_base",
                ),
                path(
                    "<str:view>/<str:action>/<str:modifier>/<int:id>",
                    self.admin_view(SBAdminEntrypointView.as_view()),
                    name="sb_admin_base",
                ),
            ]
        )
        urls.extend(super().get_urls())
        return urls


sb_admin_site = SBAdminSite(name="sb_admin")
