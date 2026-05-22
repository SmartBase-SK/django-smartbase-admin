import json
import urllib.parse

from lzstring import LZString

from django_smartbase_admin.templatetags.sb_admin_tags import SBAdminJSONEncoder

_lz = LZString()


def _is_plain_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def dumps_for_url(data) -> str:
    json_str = json.dumps(data, separators=(",", ":"), cls=SBAdminJSONEncoder)
    return _lz.compressToEncodedURIComponent(json_str)


def extract_params_from_changelist_filters(raw_filters: str) -> str | None:
    if not raw_filters:
        return None
    normalized = raw_filters.replace("+", "%2B")
    parsed = urllib.parse.parse_qs(normalized, keep_blank_values=True)
    values = parsed.get("params")
    return values[0] if values else None


def parse_changelist_filters(raw_filters: str) -> dict:
    return loads_from_url(extract_params_from_changelist_filters(raw_filters))


def loads_from_url(value: str | None) -> dict:
    if not value:
        return {}
    try:
        if _is_plain_json(value):
            data = json.loads(value)
        else:
            raw = _lz.decompressFromEncodedURIComponent(value)
            if not raw:
                return {}
            data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
