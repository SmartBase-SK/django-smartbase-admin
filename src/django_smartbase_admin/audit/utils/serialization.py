"""
Serialization utilities for audit logging.
Uses Django's built-in serialization with JSON-safe handling.
"""
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.forms.models import model_to_dict

_encoder = DjangoJSONEncoder()


def _json_safe(value):
    """Convert a value to a JSON-serializable form.

    Primitives and containers pass through (already JSON-native).
    DjangoJSONEncoder.default() handles datetime, date, time, Decimal, UUID, etc.
    Falls back to str() for anything else (ImageFieldFile, FieldFile, ...).
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    try:
        return _encoder.default(value)
    except (TypeError, ValueError):
        return str(value)


def serialize_instance(
    instance: models.Model, fields: list[str] | None = None, include_display: bool = False
) -> dict | tuple[dict, dict]:
    """
    Serialize a model instance to a JSON-safe dictionary.
    Uses Django's model_to_dict with DjangoJSONEncoder for JSON-safe values.
    
    Args:
        instance: The model instance to serialize.
        fields: Optional list of field names to include.
        include_display: If True, also return display values for FK fields.
    
    Returns:
        If include_display is False: Dictionary with field names as keys and JSON-safe values.
        If include_display is True: Tuple of (data_dict, display_dict).
    """
    if instance is None:
        return ({}, {}) if include_display else {}
    
    # Use Django's model_to_dict which handles FKs and M2Ms
    data = model_to_dict(instance, fields=fields)
    
    # Ensure all values are JSON-safe
    data = {k: _json_safe(v) for k, v in data.items()}
    
    if not include_display:
        return data
    
    # Build display values for FK fields
    display = {}
    for field in instance._meta.get_fields():
        if isinstance(field, models.ForeignKey):
            field_name = field.name
            if fields is not None and field_name not in fields:
                continue
            try:
                related_obj = getattr(instance, field_name, None)
                if related_obj is not None:
                    display[field_name] = str(related_obj)
            except Exception:
                pass  # Related object may not be accessible
    
    return data, display
