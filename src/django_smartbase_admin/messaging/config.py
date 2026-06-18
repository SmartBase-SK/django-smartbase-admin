"""
Per-project configuration surface for the messaging feature.

A project enables messaging by attaching an ``SBAdminMessagingConfig`` instance
to its ``SBAdminRoleConfiguration`` via the ``messaging_config`` attribute
(``None`` ⇒ feature disabled). The config declares:

- ``message_types``: the available message types and how each is delivered
  (small toast vs. large modal, whether the modal must be acknowledged).
- ``audiences``: pluggable recipient sources. Built-in providers cover concrete
  users, Django groups, and "all users"; a project adds a custom-model audience
  by subclassing :class:`SBAdminMessageAudience`.

All model imports are done lazily (inside methods), because this module is
imported while Django settings load — before the app registry is ready.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class NotificationStyle(models.TextChoices):
    """How a new message is surfaced to the recipient."""

    TOAST = "toast", _("Toast")
    MODAL = "modal", _("Modal")


class SBAdminMessageType:
    """A configurable message type and its notification delivery."""

    def __init__(
        self,
        key,
        label,
        notification_style=NotificationStyle.TOAST,
        icon=None,
        color=None,
        require_acknowledge=False,
    ):
        self.key = key
        self.label = label
        self.notification_style = notification_style
        # SVG sprite id (see the sb_admin icon sprite), e.g. "Info" / "Attention".
        self.icon = icon
        # Tailwind colour token used by the alert/modal partials, e.g. "notice"
        # / "warning" / "negative" / "success".
        self.color = color or "notice"
        # Only meaningful for MODAL types: require an explicit "Acknowledge"
        # click (modal is not dismissable by backdrop) before marking read.
        self.require_acknowledge = require_acknowledge

    @property
    def is_modal(self):
        return self.notification_style == NotificationStyle.MODAL


class SBAdminMessageAudience:
    """Base class for a recipient source.

    Subclass to target a custom project model. Each audience contributes one
    field to the message form (``None`` ⇒ no per-message selection, e.g. "all
    users"), knows how to serialize that field's value into the message's
    JSON ``targeting`` blob, and resolves a stored value into a user queryset.
    """

    key = None
    label = None

    def get_form_field(self, request):
        """Return the ``forms.Field`` for selecting within this audience.

        Return ``None`` for audiences that need no selection (the whole
        audience is targeted whenever it is chosen).
        """
        return None

    def serialize(self, cleaned_value):
        """Convert a cleaned form value into a JSON-serializable targeting value."""
        return cleaned_value

    def get_initial(self, stored_value):
        """Convert a stored targeting value back into a form-field initial."""
        return stored_value

    def resolve_users(self, stored_value, request):
        """Return a queryset/iterable of users for a stored targeting value."""
        raise NotImplementedError


class UsersAudience(SBAdminMessageAudience):
    """Target explicitly selected users."""

    key = "users"
    label = _("Specific users")

    def get_form_field(self, request):
        from django import forms
        from django.contrib.auth import get_user_model
        from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget

        user_model = get_user_model()
        return forms.ModelMultipleChoiceField(
            queryset=user_model.objects.all(),
            required=False,
            label=self.label,
            widget=SBAdminAutocompleteWidget(model=user_model, multiselect=True),
        )

    def serialize(self, cleaned_value):
        return [user.pk for user in cleaned_value] if cleaned_value else []

    def resolve_users(self, stored_value, request):
        from django.contrib.auth import get_user_model

        if not stored_value:
            return get_user_model().objects.none()
        return get_user_model().objects.filter(pk__in=stored_value)


class GroupsAudience(SBAdminMessageAudience):
    """Target every user in the selected Django groups."""

    key = "groups"
    label = _("User groups")

    def get_form_field(self, request):
        from django import forms
        from django.contrib.auth.models import Group
        from django_smartbase_admin.admin.widgets import SBAdminMultipleChoiceWidget

        return forms.ModelMultipleChoiceField(
            queryset=Group.objects.all(),
            required=False,
            label=self.label,
            widget=SBAdminMultipleChoiceWidget,
        )

    def serialize(self, cleaned_value):
        return [group.pk for group in cleaned_value] if cleaned_value else []

    def resolve_users(self, stored_value, request):
        from django.contrib.auth import get_user_model

        if not stored_value:
            return get_user_model().objects.none()
        return get_user_model().objects.filter(groups__in=stored_value).distinct()


class AllUsersAudience(SBAdminMessageAudience):
    """Target all active users (no per-message selection)."""

    key = "all_users"
    label = _("All users")

    def get_form_field(self, request):
        from django import forms

        return forms.BooleanField(required=False, label=self.label)

    def serialize(self, cleaned_value):
        return bool(cleaned_value)

    def resolve_users(self, stored_value, request):
        from django.contrib.auth import get_user_model

        if not stored_value:
            return get_user_model().objects.none()
        return get_user_model().objects.filter(is_active=True)


# Sensible defaults — projects can override either list wholesale.
DEFAULT_MESSAGE_TYPES = [
    SBAdminMessageType(
        key="info",
        label=_("Info"),
        notification_style=NotificationStyle.TOAST,
        icon="Info",
        color="notice",
    ),
    SBAdminMessageType(
        key="warning",
        label=_("Warning"),
        notification_style=NotificationStyle.MODAL,
        icon="Attention",
        color="warning",
        require_acknowledge=True,
    ),
]

DEFAULT_AUDIENCES = [UsersAudience(), GroupsAudience(), AllUsersAudience()]


class SBAdminMessagingConfig:
    """Top-level messaging configuration attached to ``SBAdminRoleConfiguration``."""

    def __init__(
        self,
        message_types=None,
        audiences=None,
        poll_interval_seconds=60,
    ):
        self.message_types = list(
            message_types if message_types is not None else DEFAULT_MESSAGE_TYPES
        )
        self.audiences = list(audiences if audiences is not None else DEFAULT_AUDIENCES)
        self.poll_interval_seconds = poll_interval_seconds

    # --- lookup helpers -------------------------------------------------

    def get_type_choices(self):
        return [(t.key, t.label) for t in self.message_types]

    def get_message_type(self, key):
        for message_type in self.message_types:
            if message_type.key == key:
                return message_type
        return None

    def get_audience(self, key):
        for audience in self.audiences:
            if audience.key == key:
                return audience
        return None
