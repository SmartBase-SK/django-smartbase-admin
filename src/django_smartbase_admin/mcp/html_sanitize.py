"""HTML sanitization for MCP detail values.

Admin display methods (``*_display`` callables, ``python_formatter``)
return ``mark_safe`` HTML built for the browser. ``fetch_detail`` surfaces
those values to an agent, where inline ``style`` / ``class`` / ``<script>``
is pure overhead but genuine structure (a custom ``<table>`` of values, an
FK ``<a href>``) is worth keeping.

So we *sanitize with an allowlist* rather than flattening to text (what
``list_rows`` does, where compactness across many rows wins). Structural
and layout tags — including ``div`` / ``span`` — are kept; everything that
is purely presentational or executable (all attributes bar a tiny
information-bearing set, plus ``<script>`` / ``<style>`` content) is
dropped.

Only :class:`~django.utils.safestring.SafeString` values are touched: that
is the exact signal the admin marked the value as HTML to render. Plain
strings (a description that happens to contain ``<3``) pass through
untouched.
"""

from __future__ import annotations

import re

import nh3
from django.utils.safestring import SafeString

# Structural + light-formatting tags worth keeping. ``div`` / ``span`` are
# deliberately included so custom layouts don't collapse — only their
# attributes are stripped.
_ALLOWED_TAGS: set[str] = {
    "div",
    "span",
    "p",
    "br",
    "hr",
    "a",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "small",
    "sub",
    "sup",
    "code",
    "pre",
    "ul",
    "ol",
    "li",
    "dl",
    "dt",
    "dd",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "caption",
    "colgroup",
    "col",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}

# Near-empty attribute allowlist: only attributes that carry information an
# agent can act on. Everything else (``style``, ``class``, ``id``, ``on*``,
# ``data-*``) is stripped.
_ALLOWED_ATTRS: dict[str, set[str]] = {
    "a": {"href", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
    "col": {"span"},
    "colgroup": {"span"},
}

# Tags whose *content* is removed entirely, not just unwrapped.
_DROP_CONTENT_TAGS: set[str] = {"script", "style"}

# <pre>/<code> inner whitespace is preserved; everything else is compacted.
_PRESERVE_WS_RE = re.compile(
    r"(<(?:pre|code)\b[^>]*>.*?</(?:pre|code)>)", re.DOTALL | re.IGNORECASE
)


def _collapse_whitespace(html: str) -> str:
    """Drop whitespace between tags and squeeze runs to one space, outside <pre>/<code>."""
    parts = _PRESERVE_WS_RE.split(html)
    for i, part in enumerate(parts):
        if i % 2 == 1:  # preserved <pre>/<code> block
            continue
        part = re.sub(r">\s+<", "><", part)
        parts[i] = re.sub(r"\s{2,}", " ", part)
    return "".join(parts)


def sanitize_html(value):
    """Allowlist-clean and compact a ``SafeString`` HTML value for agents.

    Keeps structural / layout markup, strips presentational and executable
    attributes, removes ``<script>`` / ``<style>`` (content included), and
    collapses template whitespace / newlines (outside ``<pre>`` / ``<code>``).
    Anything that is not a ``SafeString`` is returned unchanged, so scalars,
    relational ``{"value", "label"}`` dicts and plain strings are never
    altered.
    """
    if not isinstance(value, SafeString):
        return value
    cleaned = nh3.clean(
        str(value),
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        clean_content_tags=_DROP_CONTENT_TAGS,
        strip_comments=True,
        link_rel=None,
    )
    return _collapse_whitespace(cleaned).strip()
