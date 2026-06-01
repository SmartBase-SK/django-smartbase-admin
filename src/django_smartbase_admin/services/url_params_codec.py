import json
import urllib.parse

from lzstring import LZString

from django_smartbase_admin.templatetags.sb_admin_tags import SBAdminJSONEncoder

_lz = LZString()

# Hard caps so a short compressed URL param can't expand into a multi-megabyte
# payload (decompression + JSON-parse DoS). Deliberately very generous — orders
# of magnitude above any legitimate filter/params blob — so they only ever trip
# on abuse.
MAX_ENCODED_LEN = 256 * 1024  # raw URL param length
MAX_DECOMPRESSED_LEN = 4 * 1024 * 1024  # LZ-string decompressed output length


def _is_plain_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def dumps_for_url(data, *, compress: bool = True) -> str:
    json_str = json.dumps(data, separators=(",", ":"), cls=SBAdminJSONEncoder)
    if not compress:
        return json_str
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
    if len(value) > MAX_ENCODED_LEN:
        return {}
    try:
        if _is_plain_json(value):
            data = json.loads(value)
        else:
            raw = _lz.decompressFromEncodedURIComponent(value)
            if not raw:
                return {}
            if len(raw) > MAX_DECOMPRESSED_LEN:
                return {}
            data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
