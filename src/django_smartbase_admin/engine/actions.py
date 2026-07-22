import json

from django import forms
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.utils.translation import gettext_lazy as _


def sbadmin_action(func=None, **kwargs):
    """Mark a view method as callable via SBAdmin URL dispatch.

    Keyword arguments are stored on the function as ``_sbadmin_action_attrs``
    and propagated to the synthetic ``SBAdminCustomAction`` that
    ``delegate_to_action`` passes to ``has_permission_for_action``.

    Supported kwargs:

    - ``permission`` (str): Django model permission codename to require on the
      view's model (e.g. ``"add"``, ``"change"``, ``"delete"``, ``"view"``).
      The default ``has_action_permission`` requires ``"change"`` for any
      ``@sbadmin_action`` that does not declare a permission explicitly, so
      read-only endpoints (autocomplete, list_json, xlsx export, config, …)
      must opt in with ``permission="view"``.
    - ``mcp_components`` (str | callable): Explicitly expose the method in MCP
      discovery. A string names a bound provider method receiving ``request``;
      a callable receives ``(view, request)``. The provider must return a named
      dictionary of Django forms/formsets, or ``None`` when unavailable for
      the current request.
    - ``mcp_description`` (str): Optional description emitted with the MCP
      action schema.

    An overriding method replaces the base method's decorator metadata. It
    must therefore redeclare ``mcp_components`` when it should remain exposed.

    Usage::

        @sbadmin_action(permission="view")
        def action_list_json(self, request, modifier, object_id): ...

        @sbadmin_action(permission="delete")
        def action_delete_archived(self, request, modifier, object_id): ...
    """

    def decorator(fn):
        fn._is_sbadmin_action = True
        fn._sbadmin_action_attrs = kwargs
        return fn

    if func is not None:
        return decorator(func)
    return decorator


class TableDataEditForm(forms.Form):
    """MCP input contract for ``action_table_data_edit``.

    Field names match the existing browser POST payload so a generic MCP
    action invoker can submit the encoded form through ``delegate_to_action``.
    """

    currentRowId = forms.CharField(label=_("Row ID"))
    columnFieldName = forms.ChoiceField(label=_("Column"))
    cellValue = forms.CharField(label=_("Value"), required=False)

    def __init__(self, *args, editable_fields=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["columnFieldName"].choices = [
            (
                field.name,
                str(getattr(field, "title", None) or field.name),
            )
            for field in editable_fields
        ]

    def clean_currentRowId(self):
        row_id = self.cleaned_data["currentRowId"]
        try:
            return json.loads(row_id)
        except (TypeError, json.JSONDecodeError):
            return row_id


class SBAdminCustomAction(object):
    title = None
    url = None
    view = None
    action_id = None
    action_modifier = None
    css_class = None
    no_params = False
    open_in_modal = False
    open_in_new_tab = False
    template = None
    permission = None
    sub_actions = None
    icon = None
    mcp_description = None

    def __init__(
        self,
        title,
        url=None,
        view=None,
        action_id=None,
        action_modifier=None,
        css_class=None,
        no_params=False,
        open_in_modal=False,
        group=None,
        sub_actions=None,
        icon=None,
        open_in_new_tab=None,
        template=None,
        permission=None,
        mcp_description=None,
    ) -> None:
        super().__init__()
        self.title = title
        self.mcp_description = (
            mcp_description if mcp_description is not None else self.mcp_description
        )
        self.url = url
        self.view = view
        self.action_id = action_id
        self.action_modifier = action_modifier
        self.css_class = css_class or "btn btn-empty"
        self.no_params = no_params
        self.open_in_modal = open_in_modal
        self.group = group
        self.sub_actions = sub_actions
        self.icon = icon
        self.open_in_new_tab = open_in_new_tab
        self.template = template or "sb_admin/actions/partials/action_link.html"
        self.permission = permission
        self.validate_configuration()

    def get_action_id(self):
        """Dispatch handle for this action.

        Modal actions resolve to ``target_view.__name__`` — the same
        value ``_register_form_view_action`` assigns at registration
        time, so callers don't need to know whether registration has
        run yet. Returns ``None`` for plain-URL actions that have no
        server-side handle.
        """
        if self.action_id:
            return self.action_id
        target_view = getattr(self, "target_view", None)
        if target_view is not None:
            return target_view.__name__
        return None

    def validate_configuration(self):
        if self.sub_actions:
            return
        if not (
            self.url
            or (self.view and self.action_id)
            or getattr(self, "target_view", None) is not None
        ):
            raise ImproperlyConfigured(
                "You must provide either url, target_view, or view and action_id"
            )


class SBAdminFormViewAction(SBAdminCustomAction):
    def __init__(self, target_view, *args, **kwargs) -> None:
        self.target_view = target_view
        super().__init__(*args, **kwargs)


class SBAdminRowAction(SBAdminCustomAction):
    """Per-row icon action declared through ``sbadmin_row_actions``.

    Pass either ``sub_actions`` or exactly one of ``target_view``, ``action_id``, or ``url``:
    ``target_view`` opens a modal, ``action_id`` calls an ``@sbadmin_action``
    method, and ``url`` renders a plain link.

    Per-row enablement can be declared with ``enabled_if`` or with the simpler
    ``enabled_field``/``enabled_value`` pair. ``enabled_if`` may be a callable
    receiving the row dict and takes precedence; ``enabled_field`` renders the
    action only when ``row[enabled_field] == enabled_value``. Without either,
    the action is enabled for every row.

    ``is_download`` only applies to ``url`` actions. When set, the link is
    fetched as a blob in JS (instead of a plain browser navigation) so the
    global page-loading overlay can be shown for the whole request and hidden
    once the file is ready — useful for endpoints that take a moment to
    generate the file (e.g. shipping labels/stickers).
    """

    target_view = None
    icon = None
    css_class = "btn btn-small btn-only-icon"
    open_in_new_tab = False
    enabled_if = None
    enabled_field = None
    enabled_value = None
    is_download = False

    def __init__(
        self,
        *,
        title=None,
        icon=None,
        view=None,
        target_view=None,
        action_id=None,
        url=None,
        permission=None,
        css_class=None,
        open_in_new_tab=None,
        enabled_if=None,
        enabled_field=None,
        enabled_value=None,
        sub_actions=None,
        mcp_description=None,
        is_download=None,
    ) -> None:
        resolved_title = title if title is not None else self.title
        resolved_icon = icon if icon is not None else self.icon
        resolved_view = view if view is not None else self.view
        resolved_target_view = (
            target_view if target_view is not None else self.target_view
        )
        resolved_action_id = action_id if action_id is not None else self.action_id
        resolved_url = url if url is not None else self.url
        resolved_permission = permission if permission is not None else self.permission
        resolved_css_class = css_class if css_class is not None else self.css_class
        resolved_open_in_new_tab = (
            open_in_new_tab if open_in_new_tab is not None else self.open_in_new_tab
        )
        resolved_is_download = (
            is_download if is_download is not None else self.is_download
        )
        resolved_sub_actions = (
            sub_actions if sub_actions is not None else self.sub_actions
        )

        modes = (
            resolved_target_view is not None,
            resolved_action_id is not None,
            resolved_url is not None,
        )
        has_sub_actions = bool(resolved_sub_actions)
        if (has_sub_actions and any(modes)) or (
            not has_sub_actions and sum(modes) != 1
        ):
            raise ImproperlyConfigured(
                "SBAdminRowAction requires either sub_actions or exactly one of: "
                "target_view, action_id, url"
            )
        if resolved_sub_actions and any(modes):
            raise ImproperlyConfigured(
                "SBAdminRowAction with sub_actions cannot also define target_view, action_id, or url"
            )

        self.target_view = resolved_target_view

        super().__init__(
            title=resolved_title or "",
            view=resolved_view,
            action_id=resolved_action_id,
            url=resolved_url,
            css_class=resolved_css_class,
            open_in_modal=resolved_target_view is not None,
            open_in_new_tab=resolved_open_in_new_tab,
            icon=resolved_icon,
            sub_actions=resolved_sub_actions,
            permission=resolved_permission,
            mcp_description=mcp_description,
        )

        self.enabled_if = enabled_if if enabled_if is not None else self.enabled_if
        self.enabled_field = (
            enabled_field if enabled_field is not None else self.enabled_field
        )
        self.enabled_value = (
            enabled_value if enabled_value is not None else self.enabled_value
        )
        self.is_download = resolved_is_download

    def resolve_row_value(self, value, row):
        if callable(value):
            return value(row)
        return value

    def get_title(self, row):
        return self.resolve_row_value(self.title, row)

    def get_icon(self, row):
        return self.resolve_row_value(self.icon, row)

    def get_css_class(self, row):
        return self.resolve_row_value(self.css_class, row)

    def get_enabled_if(self, row):
        return self.resolve_row_value(self.enabled_if, row)

    def get_enabled_field(self, row):
        return self.resolve_row_value(self.enabled_field, row)

    def get_enabled_value(self, row):
        return self.resolve_row_value(self.enabled_value, row)

    def is_enabled(self, row):
        if self.enabled_if is not None:
            return bool(self.get_enabled_if(row))
        enabled_field = self.get_enabled_field(row)
        if enabled_field is not None:
            return row.get(enabled_field) == self.get_enabled_value(row)
        return True
