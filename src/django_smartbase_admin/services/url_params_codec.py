import json

from lzstring import LZString

from django_smartbase_admin.templatetags.sb_admin_tags import SBAdminJSONEncoder

_lz = LZString()


def _is_plain_json(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def dumps_for_url(data) -> str:
    json_str = json.dumps(data, separators=(",", ":"), cls=SBAdminJSONEncoder)
    return _lz.compressToEncodedURIComponent(json_str)


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
