"""Action discovery helpers for the MCP schema.

Owns the full action taxonomy so ``schema.py`` stays focused on
admin / field / inline structure:

  * **row_actions**       — per-row icon buttons on the list view
  * **detail_actions**    — buttons on the change/detail form
  * **list_actions**      — global top buttons above the list
  * **selection_actions** — bulk buttons shown when rows are selected
  * **inline_actions**    — per-inline header buttons (``SBAdminInline``)
"""

from __future__ import annotations

import base64
import json
import logging
import re
from urllib.parse import unquote

from django.contrib import messages as django_messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, QueryDict
from django.http.response import HttpResponseRedirectBase
from mcp.types import BlobResourceContents, EmbeddedResource

from django_smartbase_admin.engine.const import Action, BASE_PARAMS_NAME
from django_smartbase_admin.engine.modal_view import (
    ActionModalView,
    RowActionModalView,
)
from django_smartbase_admin.mcp.bridge import (
    captured_messages,
    ensure_messages_storage,
    set_request_payload,
)
from django_smartbase_admin.mcp.field_schema import field_info
from django_smartbase_admin.mcp.form_encoding import (
    encode_field_values,
    form_errors_dict,
    get_form_from_response,
)
from django_smartbase_admin.services.views import SBAdminViewService

logger = logging.getLogger(__name__)


# Max bytes for inline binary downloads embedded in tool responses.
# Base64 inflates ~33% and the blob lives in the conversation context,
# so cap at something that won't blow context but covers typical XLSX
# exports / small PDFs. Larger downloads fail loud rather than silently
# truncating.
MAX_INLINE_DOWNLOAD_BYTES = 5 * 1024 * 1024


def _filename_from_disposition(header: str) -> str | None:
    """Extract ``filename=...`` from a ``Content-Disposition`` header.

    Supports both the plain ``filename="..."`` and RFC 5987
    ``filename*=UTF-8''...`` forms.
    """
    if not header:
        return None
    match = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", header, re.IGNORECASE)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    match = re.search(r'filename="?([^";]+)"?', header, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def action_kind(action) -> str:
    """Classify one action as ``"method"`` | ``"modal"`` | ``"url"``.

    ``"modal"`` — has a ``target_view`` class (``SBAdminFormViewAction`` /
    ``SBAdminRowAction(target_view=...)``) that opens a form dialog.

    ``"method"`` — has an ``action_id`` referencing an
    ``@sbadmin_action``-decorated method on the admin.

    ``"url"`` — plain link with no server-side handler (e.g. the
    ``SBAdminStackedInlineBase`` "Collapse" button).
    """
    if getattr(action, "target_view", None) is not None:
        return "modal"
    if getattr(action, "action_id", None):
        return "method"
    return "url"


def action_entries_for(action) -> list[dict]:
    """Schema dicts for one action: 0, 1, or many.

    Returns the empty list for URL-only actions that have no
    server-side dispatch handle (e.g. the stacked-inline "Collapse"
    button) — agents can't invoke them, so they don't belong in
    discovery. Sub-action containers (visual dropdown groups in the UI)
    are flattened into a sibling list since each leaf is independently
    invocable.
    """
    sub_actions = getattr(action, "sub_actions", None) or []
    if sub_actions:
        flat: list[dict] = []
        for sub in sub_actions:
            # Broad except by design: discovery returns whatever it can.
            # One malformed sub-action (custom subclass, missing attrs)
            # shouldn't blank the entire admin's discovery output. The
            # full traceback goes to logs for the admin author to fix.
            try:
                flat.extend(action_entries_for(sub))
            except Exception:
                logger.warning(
                    "MCP actions: skipping sub-action %r inside %r",
                    getattr(sub, "title", sub),
                    getattr(action, "title", action),
                    exc_info=True,
                )
        return flat

    action_id = action.get_action_id()
    if action_id is None:
        return []

    # Hidden from MCP discovery — uses ``ModelAdmin.delete_queryset``
    # directly via the dedicated ``delete_objects`` tool instead.
    # Django's bulk delete renders an HTML confirmation page that doesn't
    # work cleanly through the MCP mock-request pipeline (no admin
    # session, no ``each_context``).
    if action_id == Action.BULK_DELETE.value:
        return []

    entry: dict = {
        "title": str(getattr(action, "title", "") or ""),
        "kind": action_kind(action),
        "action_id": action_id,
    }
    # ``collect_action_entries`` strips this for invoke tools that don't
    # accept a modifier (row / detail / inline route through
    # ``invoke_row`` which forces ``"template"``).
    modifier = getattr(action, "action_modifier", None)
    if modifier:
        entry["modifier"] = modifier
    target_view = getattr(action, "target_view", None)
    if target_view is not None and getattr(target_view, "requires_confirmation", False):
        entry["requires_confirmation"] = True
    return [entry]


# Maps the admin getter that produced an action list to the MCP tool an
# agent must call to invoke it. The mapping is published once at the top
# level of ``list_admins`` as ``action_invokers`` (keyed by action-list
# name, e.g. ``row_actions`` → ``invoke_row_action``) so individual
# action entries don't need to repeat ``invoke_with`` ~30 times per
# response.
_INVOKE_TOOL_BY_GETTER = {
    "get_sbadmin_row_actions_processed": "invoke_row_action",
    "get_sbadmin_detail_actions_processed": "invoke_detail_action",
    "get_sbadmin_inline_list_actions_processed": "invoke_inline_action",
    "get_sbadmin_list_actions_processed": "invoke_list_action",
    "get_sbadmin_list_selection_actions_processed": "invoke_selection_action",
}

# Top-level legend: action-list field name → MCP tool to invoke entries
# in that list. ``fieldset_actions`` are merged into ``detail_actions``.
ACTION_INVOKERS: dict[str, str] = {
    "row_actions": "invoke_row_action",
    "detail_actions": "invoke_detail_action",
    "list_actions": "invoke_list_action",
    "selection_actions": "invoke_selection_action",
    "inline_actions": "invoke_inline_action",
}


def collect_action_entries(
    source, getter_name: str, request, **getter_kwargs
) -> list[dict]:
    """Run ``source.<getter_name>(request, **getter_kwargs)`` and convert
    each action to a schema dict, tagging each entry with the MCP tool
    needed to invoke it.

    ``source`` is either an admin (for ``row_actions`` / ``detail_actions``
    / ``list_actions`` / ``selection_actions``) or an inline (for
    ``inline_actions``).
    """
    try:
        actions = getattr(source, getter_name)(request, **getter_kwargs) or []
    except Exception:
        logger.warning(
            "MCP actions: %s() failed for %s",
            getter_name,
            source.__class__.__name__,
            exc_info=True,
        )
        return []

    invoke_with = _INVOKE_TOOL_BY_GETTER.get(getter_name)
    # Only list / selection invoke tools accept a ``modifier`` parameter.
    # Strip it from entries whose invoke tool would ignore it so the
    # agent doesn't see a value it can't use.
    surface_modifier = invoke_with in {
        "invoke_list_action",
        "invoke_selection_action",
    }
    entries: list[dict] = []
    for action in actions:
        try:
            for entry in action_entries_for(action):
                if not surface_modifier:
                    entry.pop("modifier", None)
                entries.append(entry)
        except Exception:
            logger.warning(
                "MCP actions: skipping action %r on %s",
                getattr(action, "title", action),
                source.__class__.__name__,
                exc_info=True,
            )
    return entries


def build_modal_view(target_view_cls, admin, request, modifier, object_id=None):
    """Construct and bind a modal view to admin / request / modifier.

    Shared by form discovery (``get_action_form_data``), unbound-form
    construction for invoke (``_build_unbound_form``), and the
    rebuild-for-error-extraction step (``_normalize_modal_response``).
    Caller switches ``request.method`` as needed. ``object_id`` mirrors
    the URL kwarg ``RowActionModalView.get_object_id`` looks up first,
    so the unbound-form build can resolve the row even though the real
    ``delegate_to_action`` hasn't run yet to populate ``request_data``.
    """
    view = target_view_cls(view=admin)
    view.request = request
    kwargs: dict = {}
    if modifier is not None:
        kwargs["modifier"] = modifier
    if object_id is not None:
        kwargs["object_id"] = object_id
        # ``RowActionModalView.get_object_id`` checks
        # ``request_data.object_id`` first — populate it so the
        # fallback to ``kwargs["modifier"]`` doesn't pick up
        # ``"template"`` and miscast it as a pk.
        rd = getattr(request, "request_data", None)
        if rd is not None:
            rd.object_id = object_id
    view.kwargs = kwargs
    return view


class SBAdminMCPActionFormService:
    """Form discovery for modal actions — counterpart to ``fetch_add_form``.

    Entry point: :meth:`get_action_form_data`. Stateless classmethods that
    take an already-resolved admin instance.
    """

    @classmethod
    def get_action_form_data(
        cls,
        admin,
        request,
        action_id: str,
        object_id: str | None = None,
    ) -> dict:
        """Return ``{"title", "fields"}`` for a modal action.

        For ``RowActionModalView``-based actions pass ``object_id`` so
        the form can be pre-populated with the instance.

        See the ``fetch_action_form`` MCP tool docstring for the exact
        return shape per field.

        Raises ``LookupError`` if ``action_id`` is not found among the
        admin's modal actions, or when ``object_id`` is required but the
        object is not visible. Raises ``PermissionDenied`` if the action
        is gated by a permission the user does not hold.
        """
        _, target_view_cls = cls._find_modal_action(admin, action_id, request)

        # Going through view.get_form() (instead of constructing the form
        # class directly) is the only way to honour subclass overrides of
        # get_form_kwargs() — that's where custom-init forms get their
        # bespoke keyword arguments (e.g. EditEmergencyForm requires
        # emergency=<obj>, injected by the view, not the form class).
        view = build_modal_view(
            target_view_cls,
            admin,
            request,
            str(object_id) if object_id is not None else None,
        )

        if object_id is not None and issubclass(target_view_cls, RowActionModalView):
            if view.get_object() is None:
                raise LookupError(
                    f"Object pk={object_id!r} not visible in admin {admin.get_id()!r}."
                )

        # MCP transport is JSON-RPC over POST; force GET while building
        # form kwargs so FormMixin doesn't try to parse request.POST as
        # form data. set_request_payload keeps request.method and
        # request_data.request_method in sync (the latter is the channel
        # SBAdmin widget / form code reads from).
        saved_method = request.method
        set_request_payload(request, method="GET")
        try:
            form = view.get_form()
        finally:
            set_request_payload(request, method=saved_method)

        try:
            title = view.get_modal_title()
        except Exception:
            title = getattr(target_view_cls, "modal_title", "")
        return {
            "title": str(title or ""),
            "fields": cls._form_field_schema(form),
        }

    @classmethod
    def _find_modal_action(cls, view, action_id: str, request):
        """Search ``view``'s action sources for a modal action.

        ``view`` is either an admin (walks the four admin-level lists)
        or an inline (walks ``get_sbadmin_inline_list_actions``).
        Inlines register in ``view_map`` under their own ``get_id()``
        and dispatch through their own URL namespace, so an inline
        invocation lands here with the inline as ``view``.
        """
        for action_list in cls._action_sources(view, request):
            for action in action_list or []:
                found = cls._search_action_tree(action, action_id)
                if found is not None:
                    return found

        raise LookupError(
            f"No modal action {action_id!r} on view {view.get_id()!r}. "
            f"action_id must be a target_view class name from list_admins()."
        )

    @classmethod
    def _action_sources(cls, view, request):
        """Yield the right action lists for ``view`` (admin vs. inline).

        ``_processed`` variants run ``process_actions_permissions``, so
        actions the user can't invoke don't get a form fetch — lookup
        fails with the same ``LookupError`` as a missing action, and
        permission is enforced consistently with the UI and the invoke
        path.
        """
        if hasattr(view, "get_sbadmin_inline_list_actions_processed"):
            yield view.get_sbadmin_inline_list_actions_processed(request)
            return
        yield view.get_sbadmin_row_actions_processed(request)
        yield view.get_sbadmin_detail_actions_processed(request)
        yield view.get_sbadmin_list_selection_actions_processed(request)
        yield view.get_sbadmin_list_actions_processed(request)
        # Fieldset-scoped actions dispatch through the same detail path,
        # so include them in the modal-action lookup. ``object_id=None``
        # for discovery / form-fetch; invoke supplies it via ``modifier``.
        yield view.get_sbadmin_fieldsets_actions_processed(request)

    @classmethod
    def _search_action_tree(cls, action, action_id: str):
        """DFS for a modal action whose ``get_action_id()`` matches.
        Returns ``(action, target_view_class)`` or ``None``. Only modal
        actions (those with a ``target_view``) are returned — method
        actions with the same ``action_id`` aren't form-fetchable.
        """
        target_view = getattr(action, "target_view", None)
        if target_view is not None and action.get_action_id() == action_id:
            return action, target_view

        for sub in getattr(action, "sub_actions", None) or []:
            found = cls._search_action_tree(sub, action_id)
            if found is not None:
                return found

        return None

    @classmethod
    def _form_field_schema(cls, form) -> dict:
        """Walk ``form.fields`` into ``{name: info}`` via the shared
        ``field_info`` helper. See ``mcp.field_schema.field_info`` for
        the per-field dict shape.
        """
        result: dict = {}
        for name, field in form.fields.items():
            # Bound initial wins over field-level default.
            initial = (form.initial or {}).get(name)
            if initial is None:
                raw = field.initial
                initial = raw() if callable(raw) else raw

            result[name] = field_info(field, initial, label=str(field.label or name))
        return result


class SBAdminMCPActionInvokeService:
    """Invocation for row / selection / list actions.

    Three public entry points — :meth:`invoke_row`, :meth:`invoke_selection`,
    :meth:`invoke_list` — each routing through
    ``SBAdminViewService.delegate_to_action`` (the same gate the UI uses)
    with the right modifier / POST / BASE_PARAMS shape per action type.

    Method-kind and modal-kind actions are auto-detected: ``action_id``
    is looked up against the admin's modal actions; if found, the form
    submission path is used with ``field_values``; otherwise we treat it
    as a method action and ``field_values`` must be absent.
    """

    # -- public --------------------------------------------------------------

    @classmethod
    def delete_objects(
        cls,
        admin,
        request,
        object_ids: list,
        confirmed: bool = False,
    ) -> dict:
        """Delete one or more objects through ``ModelAdmin.delete_queryset``.

        Two-step like the modal confirmation flow: the first call returns
        ``{"status": "needs_confirmation", "data": {"count", "sample",
        "cascade"}, "message": ...}``; passing ``confirmed=True`` executes
        the delete. Bypasses Django's HTML ``delete_selected`` confirmation
        view (which doesn't render outside a real admin session) and goes
        straight through the admin's delete hook so audit + signals fire
        as they would on any other delete.
        """
        if not object_ids:
            raise ValueError("delete_objects requires a non-empty object_ids list.")
        if not admin.has_delete_permission(request):
            raise PermissionError(
                f"User has no delete permission on admin {type(admin).__name__}."
            )

        pk_name = admin.model._meta.pk.name
        queryset = admin.get_queryset(request).filter(**{f"{pk_name}__in": object_ids})

        _, model_count, perms_needed, protected = admin.get_deleted_objects(
            queryset, request
        )

        if perms_needed:
            raise PermissionError(
                f"Missing delete permission for related models: {sorted(perms_needed)}"
            )

        if protected:
            return {
                "status": "invalid",
                "errors": {
                    "non_field": [
                        f"Cannot delete — protected by: {p}" for p in protected
                    ]
                },
            }

        count = queryset.count()
        opts = admin.model._meta
        verbose = opts.verbose_name if count == 1 else opts.verbose_name_plural

        if not confirmed:
            return {
                "status": "needs_confirmation",
                "data": {
                    "count": count,
                    "sample": [str(obj) for obj in queryset[:10]],
                    "cascade": dict(model_count),
                },
                "message": f"Delete {count} {verbose}?",
            }

        ensure_messages_storage(request)
        admin.delete_queryset(request, queryset)
        django_messages.success(request, f"Deleted {count} {verbose}.")
        return {"status": "ok", "messages": captured_messages(request)}

    @classmethod
    def invoke_row(
        cls,
        admin,
        request,
        action_id: str,
        object_id: str,
        field_values: dict | None = None,
        confirmed: bool = False,
    ) -> dict:
        """Invoke a row / detail / inline action against one object.

        For modal-kind actions, ``field_values`` is the form submission;
        for method-kind actions it must be ``None`` / empty. Set
        ``confirmed=True`` after seeing a ``needs_confirmation`` response.
        Object id flows through ``request_data.object_id`` (the same URL
        kwarg slot the UI uses), not through ``modifier``.
        """
        return cls._invoke(
            admin,
            request,
            action_id=action_id,
            modifier="template",
            object_id=str(object_id),
            field_values=field_values,
            confirmed=confirmed,
        )

    @classmethod
    def invoke_selection(
        cls,
        admin,
        request,
        action_id: str,
        object_ids: list,
        field_values: dict | None = None,
        confirmed: bool = False,
        modifier: str | None = None,
    ) -> dict:
        """Invoke a selection (bulk) action over an explicit list of ids.

        Mode A only — ``object_ids`` is the canonical, explicit selection.
        Empty list rejected so accidental "act on everything" is impossible.
        Set ``confirmed=True`` after seeing a ``needs_confirmation`` response.
        ``modifier`` is the action's ``action_modifier`` as surfaced in
        discovery; defaults to ``"template"`` (matches URL dispatch's
        fallback when no modifier is declared).
        """
        if not object_ids:
            raise ValueError(
                "invoke_selection_action requires a non-empty object_ids list."
            )
        return cls._invoke(
            admin,
            request,
            action_id=action_id,
            modifier=modifier or "template",
            field_values=field_values,
            confirmed=confirmed,
            base_params={
                admin.get_id(): {
                    "selectionData": {
                        "table_selected_rows": [str(i) for i in object_ids],
                        "table_deselected_rows": [],
                    }
                }
            },
        )

    @classmethod
    def invoke_list(
        cls,
        admin,
        request,
        action_id: str,
        field_values: dict | None = None,
        filter_data: dict | None = None,
        full_text_search: str | None = None,
        confirmed: bool = False,
        modifier: str | None = None,
    ) -> dict:
        """Invoke a list-level action (no row context).

        ``filter_data`` / ``full_text_search`` are passed through to
        filter-aware actions; ignored by actions that don't consult them.
        ``modifier`` is the action's ``action_modifier`` from discovery
        (e.g. ``IGNORE_LIST_SELECTION`` for whole-list exports);
        defaults to ``"template"``. Set ``confirmed=True`` after seeing
        a ``needs_confirmation`` response.
        """
        base_params = None
        if filter_data or full_text_search:
            filter_payload = dict(filter_data or {})
            if full_text_search:
                filter_payload["sbadmin_full_text_search"] = full_text_search
            base_params = {admin.get_id(): {"filterData": filter_payload}}
        return cls._invoke(
            admin,
            request,
            action_id=action_id,
            modifier=modifier or "template",
            field_values=field_values,
            confirmed=confirmed,
            base_params=base_params,
        )

    # -- shared dispatch -----------------------------------------------------

    @classmethod
    def _invoke(
        cls,
        admin,
        request,
        *,
        action_id: str,
        modifier: str | None,
        field_values: dict | None,
        object_id: str | None = None,
        base_params: dict | None = None,
        confirmed: bool = False,
    ) -> dict:
        modal = cls._lookup_modal_action(admin, action_id, request)

        if modal is None:
            if field_values:
                raise LookupError(
                    f"Action {action_id!r} is not a modal action; "
                    f"field_values is only valid for modal actions."
                )
            post_qd = QueryDict(mutable=True)
        else:
            _action, target_view_cls = modal
            # Wire up the synthetic @sbadmin_action wrapper if the UI
            # render path hasn't already done so this process.
            if not hasattr(admin, action_id):
                admin._register_form_view_action(target_view_cls, action_id, _action)
            # Widget-aware POST encoding: build the form unbound to get
            # the widget map, then route field_values through each
            # widget (handles MultiWidget, autocomplete list-shape, etc.).
            unbound_form = cls._build_unbound_form(
                target_view_cls, admin, request, modifier, object_id=object_id
            )
            post_qd = encode_field_values(unbound_form, field_values or {})
            if confirmed:
                post_qd[ActionModalView.CONFIRMATION_POST_KEY] = "1"

        get_payload = None
        if base_params is not None:
            get_payload = {BASE_PARAMS_NAME: json.dumps(base_params)}

        set_request_payload(
            request,
            get=get_payload,
            post=post_qd,
            method="POST",
        )

        # Capture user-facing messages the view emits via Django's messages
        # framework (e.g. ``messages.success("Created formula 'X'")``) so
        # they surface in the response instead of being dropped.
        ensure_messages_storage(request)

        try:
            response = SBAdminViewService.delegate_to_action(
                request,
                view=admin.get_id(),
                action=action_id,
                modifier=modifier,
                object_id=object_id,
            )
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc
        except Http404:
            # Unknown action_id falls through dispatch to a bare
            # (empty-message) Http404; give a clear, named error instead.
            raise LookupError(
                f"No invocable action {action_id!r} on view "
                f"{admin.get_id()!r}. action_id must come from "
                f"list_admins()'s row/detail/list/selection_actions."
            )

        if modal is None:
            result = cls._normalize_method_response(response)
        else:
            result = cls._normalize_modal_response(
                response,
                target_view_cls=modal[1],
                admin=admin,
                request=request,
                modifier=modifier,
            )
        messages = captured_messages(request)
        if messages:
            if isinstance(result, dict):
                result["messages"] = messages
            else:
                # Binary-download path: result is a list of content
                # blocks. Surface messages as their own JSON text block
                # ahead of the embedded resource.
                result.insert(1, json.dumps({"messages": messages}))
        return result

    # -- helpers -------------------------------------------------------------

    @classmethod
    def _lookup_modal_action(cls, admin, action_id, request):
        """Return ``(action, target_view_cls)`` if ``action_id`` matches a
        modal action on this admin; ``None`` for method actions (so the
        caller treats them as plain ``@sbadmin_action`` dispatch).
        """
        try:
            return SBAdminMCPActionFormService._find_modal_action(
                admin, action_id, request
            )
        except LookupError:
            return None

    @classmethod
    def _build_unbound_form(
        cls, target_view_cls, admin, request, modifier, object_id=None
    ):
        """Construct the modal view's form without binding POST data.

        Mirrors :meth:`SBAdminMCPActionFormService.get_action_form_data`'s
        form-construction path: drives ``view.get_form()`` under method=GET
        so subclass overrides of ``get_form_kwargs`` (custom-init kwargs
        like ``emergency=<obj>``) run, but no POST data is consumed yet.
        Used by invoke to introspect the widget map before encoding the
        agent's submission.
        """
        view = build_modal_view(
            target_view_cls, admin, request, modifier, object_id=object_id
        )

        saved_method = request.method
        set_request_payload(request, method="GET")
        try:
            return view.get_form()
        finally:
            set_request_payload(request, method=saved_method)

    @classmethod
    def _normalize_method_response(cls, response) -> dict:
        """Convert a method action's HTTP response to ``{"status", ...}``."""
        status = getattr(response, "status_code", 200)
        if status >= 400:
            return {"status": "error", "http_status": status}

        if isinstance(response, HttpResponseRedirectBase):
            return {"status": "ok", "redirect": response["Location"]}

        content_type = (
            response.get("Content-Type", "") if hasattr(response, "get") else ""
        )
        if "application/json" in content_type:
            try:
                data = json.loads(response.content.decode())
                return {"status": "ok", **data}
            except Exception:
                pass

        # Binary download — embed as an MCP resource so the client can
        # save it as a file. Text/JSON falls through to ``{"status": "ok"}``.
        if content_type and not content_type.startswith(("text/", "application/json")):
            bytes_content = getattr(response, "content", b"") or b""
            if bytes_content:
                if len(bytes_content) > MAX_INLINE_DOWNLOAD_BYTES:
                    return {
                        "status": "error",
                        "message": (
                            f"File too large to embed inline "
                            f"({len(bytes_content)} bytes; max "
                            f"{MAX_INLINE_DOWNLOAD_BYTES})."
                        ),
                    }
                filename = (
                    _filename_from_disposition(response.get("Content-Disposition", ""))
                    or "download"
                )
                return [
                    json.dumps(
                        {
                            "status": "ok",
                            "file": {
                                "filename": filename,
                                "size": len(bytes_content),
                                "content_type": content_type,
                            },
                        }
                    ),
                    EmbeddedResource(
                        type="resource",
                        resource=BlobResourceContents(
                            uri=f"resource://sbadmin/{filename}",
                            mimeType=content_type,
                            blob=base64.b64encode(bytes_content).decode("utf-8"),
                        ),
                    ),
                ]
        return {"status": "ok"}

    @classmethod
    def _normalize_modal_response(
        cls,
        response,
        *,
        target_view_cls,
        admin,
        request,
        modifier,
    ) -> dict:
        """Modal success/failure detection via HX-Trigger from
        ``build_success_response`` — form_invalid responses don't carry
        ``hideModal``. On failure, re-run the form to extract structured
        errors instead of parsing the rendered template.
        """
        hx_trigger = ""
        if hasattr(response, "headers"):
            hx_trigger = response.headers.get("HX-Trigger", "") or ""
        if "hideModal" in hx_trigger:
            return {"status": "ok"}
        if "sbadminConfirmationRequired" in hx_trigger:
            return cls._build_needs_confirmation(hx_trigger)

        # Validation failed (or the view added an error programmatically
        # via ``SBAdminActionError`` → ``form_invalid``). The authoritative
        # form state lives in the rendered template's context — read errors
        # from there rather than rebuilding the form, so we capture
        # non-field errors the view added after validation.
        form = get_form_from_response(response, "form")
        if form is not None:
            return {"status": "invalid", "errors": form_errors_dict(form)}

        # Fallback: response wasn't a TemplateResponse with a form in
        # context. Rebuild the form to surface whatever validation errors
        # the original dispatch would have raised.
        view = build_modal_view(target_view_cls, admin, request, modifier)
        if modifier is not None and issubclass(target_view_cls, RowActionModalView):
            view.get_object()
        form = view.get_form()
        form.is_valid()
        set_request_payload(request, method="GET")
        return {"status": "invalid", "errors": form_errors_dict(form)}

    @classmethod
    def _build_needs_confirmation(cls, hx_trigger: str) -> dict:
        """Parse the ``sbadminConfirmationRequired`` HX-Trigger payload
        into top-level ``message`` and ``data``."""
        try:
            events = json.loads(hx_trigger)
        except Exception:
            events = {}
        data = dict(events.get("sbadminConfirmationRequired") or {})
        message = data.pop("_message", None)
        result: dict = {"status": "needs_confirmation", "data": data}
        if message is not None:
            result["message"] = message
        return result
