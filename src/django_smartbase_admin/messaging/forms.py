"""Dynamic message form.

The form's ``type`` choices and per-audience selection fields are driven by the
project's messaging config, so they are built per-request as a dynamic subclass
(see :func:`build_message_form_class`, used by ``MessageAdmin.get_form``). The
audience fields are *declared* on the generated class so Django's
``modelform_factory`` keeps them even though they are not model fields.
"""

from django import forms

from django_smartbase_admin.admin.admin_base import SBAdminBaseForm
from django_smartbase_admin.messaging.models import Message

AUDIENCE_FIELD_PREFIX = "audience_"


class MessageForm(SBAdminBaseForm):
    class Meta:
        model = Message
        # ``content`` is a RichTextField → the framework maps its
        # RichTextFormField to SBAdminCKEditorWidget automatically.
        fields = ["title", "type", "content"]


def audience_field_name(audience_key):
    return f"{AUDIENCE_FIELD_PREFIX}{audience_key}"


def build_message_form_class(messaging_config, request):
    """Build a ``MessageForm`` subclass with config-driven type + audience fields."""
    attrs = {
        "__module__": MessageForm.__module__,
        "type": forms.ChoiceField(
            choices=messaging_config.get_type_choices(),
            label=Message._meta.get_field("type").verbose_name,
        ),
    }

    audiences = []
    for audience in messaging_config.audiences:
        field = audience.get_form_field(request)
        if field is None:
            continue
        name = audience_field_name(audience.key)
        attrs[name] = field
        audiences.append(audience)

    def __init__(self, *args, **kwargs):
        super(form_class, self).__init__(*args, **kwargs)
        # Repopulate audience fields from the instance's stored targeting on edit.
        instance = getattr(self, "instance", None)
        targeting = getattr(instance, "targeting", None) or {}
        for audience in audiences:
            name = audience_field_name(audience.key)
            if name in self.fields and audience.key in targeting:
                self.fields[name].initial = audience.get_initial(
                    targeting[audience.key]
                )

    attrs["__init__"] = __init__
    attrs["_sbadmin_audiences"] = audiences

    form_class = type("DynamicMessageForm", (MessageForm,), attrs)
    return form_class
