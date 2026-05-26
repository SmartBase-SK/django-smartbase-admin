"""Hydrate ``_inlines`` onto MCP ``list_rows`` payloads."""

from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied

from django_smartbase_admin.engine.fake_inline import (
    FakeInlineFilterOverrideMismatchError,
)
from django_smartbase_admin.mcp.service import SBAdminMCPDetailService

logger = logging.getLogger(__name__)


def attach_inlines(admin, request, rows: list[dict], include_inlines) -> None:
    """Mutate ``rows`` in place: add ``_inlines[<name>]`` and, when capped,
    ``_truncated_inlines: [<name>, ...]``. Each spec must be
    ``{"inline_name": "...", "fields": [...]}``.

    Inline class lookup is restricted to inlines the admin actually declares
    (real or fake) — agent cannot reach an arbitrary inline class.
    """
    if not rows or not include_inlines:
        return

    available = {cls.__name__: cls for cls in (admin.get_inlines(request, None) or [])}
    available.update(
        {
            cls.__name__: cls
            for cls in admin.get_sbadmin_fake_inlines(request, obj=None) or []
        }
    )

    pk_name = admin.model._meta.pk.name
    by_pk = {row[pk_name]: row for row in rows if pk_name in row}
    parent_pks = list(by_pk.keys())
    if not parent_pks:
        return

    for spec in include_inlines:
        if not isinstance(spec, dict):
            raise TypeError(
                "Inline specs must be objects like "
                "{'inline_name': 'InlineClassName', 'fields': ['field_name']}."
            )
        inline_name = spec.get("inline_name")
        fields = spec.get("fields")
        if not inline_name:
            raise TypeError("Inline spec requires 'inline_name'.")
        if not isinstance(fields, list) or not fields:
            raise TypeError(
                f"Inline spec {inline_name!r} requires a non-empty 'fields' list."
            )

        inline_class = available.get(inline_name)
        if inline_class is None:
            raise LookupError(
                f"Inline {inline_name!r} not declared on view_id={admin.get_id()!r}; "
                f"available: {sorted(available)}."
            )

        inline = inline_class(admin.model, admin.admin_site)
        inline.init_inline_dynamic(request, None)
        try:
            grouped, truncated = SBAdminMCPDetailService.get_data_for_parents(
                inline, request, parent_pks, fields=fields
            )
        except FakeInlineFilterOverrideMismatchError as exc:
            logger.warning("Skipping inline %s: %s", inline_name, exc)
            continue
        except PermissionDenied as exc:
            raise PermissionError(str(exc)) from exc
        for pk, items in grouped.items():
            row = by_pk.get(pk)
            if row is None:
                continue
            row.setdefault("_inlines", {})[inline_name] = items
        for pk in truncated:
            row = by_pk.get(pk)
            if row is None:
                continue
            row.setdefault("_truncated_inlines", []).append(inline_name)
