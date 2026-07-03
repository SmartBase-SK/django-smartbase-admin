import json
from dataclasses import dataclass, field

from django import forms
from django.apps import apps as django_apps
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured
from django.utils.text import capfirst
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.admin.widgets import SBAdminBaseWidget


@dataclass
class PermissionOption:
    """One visible permission switch backed by one or more Django permissions."""

    label: str
    """Display name for the visible permission option."""

    codenames: list[str]
    """Strict permission refs in ``app_label.model:codename`` format."""

    help_text: str = ""
    """Help text displayed below the option label."""


@dataclass
class PermissionGroup:
    """Declarative business group for :class:`SBAdminPermissionWidget`."""

    label: str
    """Display name for the group section."""

    options: list[PermissionOption] = field(default_factory=list)
    """Visible permission options. Each option can map to multiple permissions."""

    help_text: str = ""
    """Help text displayed below the group header."""


@dataclass(frozen=True)
class PermissionData:
    """Scalar permission data needed to render :class:`SBAdminPermissionWidget`."""

    id: int
    name: str
    codename: str
    app_label: str
    app_verbose: str
    model_name: str
    model_verbose: str


STANDARD_ACTIONS = ("view", "add", "change", "delete")
STANDARD_ACTION_LABELS = {
    "view": _("View"),
    "add": _("Create"),
    "change": _("Edit"),
    "delete": _("Delete"),
}


@dataclass
class PermissionRenderRow:
    """Single checkbox row rendered by ``permission_tree.html``."""

    id: int | str
    name: str
    permission_ids: list[int]
    selected: bool
    search_text: str
    codename: str = ""
    help_text: str = ""

    @property
    def value(self):
        return self.permission_ids[0] if self.permission_ids else ""

    @property
    def permission_ids_json(self):
        return json.dumps(self.permission_ids)


@dataclass
class PermissionRenderCell:
    """One standard action cell in a model permission row."""

    action: str
    label: str
    permission: PermissionRenderRow | None


@dataclass
class PermissionRenderModel:
    """Template DTO for one model or user-defined option group."""

    model_name: str
    model_verbose: str
    show_header: bool = True
    standard_perms: dict[str, PermissionRenderRow] = field(default_factory=dict)
    custom_perms: list[PermissionRenderRow] = field(default_factory=list)

    @property
    def has_standard_permissions(self):
        return any(self.standard_perms.values())

    @property
    def has_custom_permissions(self):
        return bool(self.custom_perms)

    @property
    def standard_cells(self):
        return [
            PermissionRenderCell(
                action=action,
                label=STANDARD_ACTION_LABELS[action],
                permission=self.standard_perms.get(action),
            )
            for action in STANDARD_ACTIONS
        ]

    @property
    def standard_search_text(self):
        return " ".join(
            permission.search_text
            for permission in self.standard_perms.values()
            if permission is not None
        )

    @property
    def permission_count(self):
        return sum(
            1 for permission in self.standard_perms.values() if permission
        ) + len(self.custom_perms)

    @property
    def selected_count(self):
        return sum(
            1
            for permission in self.standard_perms.values()
            if permission is not None and permission.selected
        ) + sum(1 for permission in self.custom_perms if permission.selected)


@dataclass
class PermissionRenderSection:
    """Template DTO for one collapsible permission section."""

    key: str
    label: str
    help_text: str = ""
    models: list[PermissionRenderModel] = field(default_factory=list)

    @property
    def permissions_count(self):
        return sum(model.permission_count for model in self.models)

    @property
    def selected_count(self):
        return sum(model.selected_count for model in self.models)

    @property
    def has_standard_permissions(self):
        return any(model.has_standard_permissions for model in self.models)

    @property
    def has_custom_permissions(self):
        return any(model.has_custom_permissions for model in self.models)


class SBAdminPermissionWidget(SBAdminBaseWidget, forms.Widget):
    """Collapsible, searchable permission tree widget for ``auth.Permission``.

    Two modes:

    **Default mode** — groups permissions by ``app_label`` / model.  Every
    Django permission is shown.  Use this when you want the full permission
    tree without any filtering.

    **Groups mode** — pass ``groups`` (a list of :class:`PermissionGroup`)
    to define user-facing permission options. Each option resolves one or more
    strict ``app_label.model:codename`` refs against the widget queryset.

    Unbound forms select no permissions by default. Pass ``preselect_all=True``
    only when a new object should intentionally start with every queryset
    permission selected.
    """

    template_name = "sb_admin/widgets/permission_tree.html"

    class Media:
        js = [
            "sb_admin/dist/permission_tree.js",
        ]

    def __init__(
        self,
        form_field=None,
        attrs=None,
        groups=None,
        queryset=None,
        preselect_all=False,
    ):
        super().__init__(
            form_field,
            attrs={"class": "permission-tree", **(attrs or {})},
        )
        self._groups = groups or []
        self.queryset = queryset
        self.preselect_all = preselect_all

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        permissions = self._get_permission_data()
        selected = self._parse_selected_permission_ids(value)
        if value is None and self.preselect_all:
            selected = self._get_default_selected_ids(permissions)

        sections = self._build_group_context(selected, permissions)

        context["widget"]["permission_sections"] = sections
        context["widget"]["standard_action_headers"] = [
            {"action": action, "label": STANDARD_ACTION_LABELS[action]}
            for action in STANDARD_ACTIONS
        ]
        context["widget"]["selected_values"] = json.dumps(list(selected))
        return context

    def _build_auto_context(self, selected, permissions, exclude_ids=None):
        """Build context grouping permissions by app_label → model."""
        exclude_ids = exclude_ids or set()
        sections = []
        current_app = None
        current_model = None
        section = None
        model = None

        for permission in permissions:
            if permission.id in exclude_ids:
                continue

            ct_key = (permission.app_label, permission.model_name)

            if current_app != permission.app_label:
                section = PermissionRenderSection(
                    key=permission.app_label,
                    label=permission.app_verbose,
                )
                sections.append(section)
                current_app = permission.app_label
                current_model = None

            if current_model != ct_key:
                model = PermissionRenderModel(
                    model_name=permission.model_name,
                    model_verbose=permission.model_verbose,
                )
                section.models.append(model)
                current_model = ct_key

            is_standard = self._is_standard_codename(
                permission.codename, permission.model_name
            )
            action = self._standard_action(permission.codename) if is_standard else None
            row = PermissionRenderRow(
                id=permission.id,
                codename=permission.codename,
                name=(
                    STANDARD_ACTION_LABELS.get(action, permission.name)
                    if is_standard
                    else permission.name
                ),
                permission_ids=[permission.id],
                selected=permission.id in selected,
                search_text=(
                    f"{permission.name} {permission.codename} "
                    f"{permission.model_verbose}"
                ),
            )

            if is_standard:
                model.standard_perms[action] = row
            else:
                model.custom_perms.append(row)

        return sections

    def _build_group_context(self, selected, permissions):
        permissions_by_ref = {}
        if self._groups:
            permissions_by_ref = {
                self._permission_ref(permission): permission
                for permission in permissions
            }

        sections = []
        seen_permission_ids = set()
        for group_idx, group in enumerate(self._groups):
            custom_perms = []
            for option_idx, option in enumerate(group.options):
                if not option.codenames:
                    raise ImproperlyConfigured(
                        "PermissionOption.codenames must define at least one "
                        "permission ref."
                    )
                option_permissions = [
                    self._resolve_permission_ref(ref, permissions_by_ref)
                    for ref in option.codenames
                ]
                permission_ids = [permission.id for permission in option_permissions]
                seen_permission_ids.update(permission_ids)
                custom_perms.append(
                    PermissionRenderRow(
                        id=f"group-{group_idx}-option-{option_idx}",
                        name=option.label,
                        help_text=option.help_text,
                        permission_ids=permission_ids,
                        selected=all(
                            permission_id in selected
                            for permission_id in permission_ids
                        ),
                        search_text=f"{option.label} {option.help_text}",
                    )
                )

            sections.append(
                PermissionRenderSection(
                    key=f"group-{group_idx}",
                    label=group.label,
                    help_text=group.help_text,
                    models=[
                        PermissionRenderModel(
                            model_name=f"group-{group_idx}",
                            model_verbose="",
                            show_header=False,
                            custom_perms=custom_perms,
                        )
                    ],
                )
            )
        sections.extend(
            self._build_auto_context(
                selected,
                permissions,
                exclude_ids=seen_permission_ids,
            )
        )
        return sections

    @staticmethod
    def _app_verbose_name(app_label):
        try:
            app_config = django_apps.get_app_config(app_label)
        except LookupError:
            return app_label.replace("_", " ").title()
        return app_config.verbose_name

    @staticmethod
    def _model_verbose_name(app_label, model_name):
        try:
            model_class = django_apps.get_model(app_label, model_name)
        except LookupError:
            model_class = None
        if model_class is not None:
            return capfirst(model_class._meta.verbose_name)
        return capfirst(model_name.replace("_", " "))

    # ------------------------------------------------------------------
    # Permission resolution helpers
    # ------------------------------------------------------------------

    def _get_permission_queryset(self):
        if self.queryset is not None:
            return self.queryset
        if self.form_field is not None and hasattr(self.form_field, "queryset"):
            return self.form_field.queryset
        choices_field = getattr(getattr(self, "choices", None), "field", None)
        if choices_field is not None and hasattr(choices_field, "queryset"):
            return choices_field.queryset
        return Permission.objects.none()

    def _get_permission_data(self):
        qs = (
            self._get_permission_queryset()
            .order_by("content_type__app_label", "content_type__model", "codename")
            .values(
                "id",
                "name",
                "codename",
                "content_type__app_label",
                "content_type__model",
            )
        )
        app_verbose_by_label = {}
        model_verbose_by_key = {}
        permissions = []

        for row in qs:
            app_label = row["content_type__app_label"]
            model_name = row["content_type__model"]
            model_key = (app_label, model_name)
            if app_label not in app_verbose_by_label:
                app_verbose_by_label[app_label] = self._app_verbose_name(app_label)
            if model_key not in model_verbose_by_key:
                model_verbose_by_key[model_key] = self._model_verbose_name(
                    app_label,
                    model_name,
                )
            permissions.append(
                PermissionData(
                    id=row["id"],
                    name=row["name"],
                    codename=row["codename"],
                    app_label=app_label,
                    app_verbose=app_verbose_by_label[app_label],
                    model_name=model_name,
                    model_verbose=model_verbose_by_key[model_key],
                )
            )
        return permissions

    @staticmethod
    def _get_default_selected_ids(permissions):
        return {permission.id for permission in permissions}

    @staticmethod
    def _permission_ref(permission):
        return f"{permission.app_label}.{permission.model_name}:{permission.codename}"

    @staticmethod
    def _resolve_permission_ref(ref, permissions_by_ref):
        SBAdminPermissionWidget._validate_permission_ref(ref)
        permission = permissions_by_ref.get(ref)
        if permission is None:
            raise ImproperlyConfigured(
                f"Permission ref '{ref}' was not found in "
                "SBAdminPermissionWidget queryset."
            )
        return permission

    @staticmethod
    def _validate_permission_ref(ref):
        if not isinstance(ref, str) or ref.count(":") != 1:
            raise ImproperlyConfigured(
                "Permission refs must use 'app_label.model:codename' format."
            )
        model_ref, codename = ref.split(":", 1)
        if model_ref.count(".") != 1:
            raise ImproperlyConfigured(
                "Permission refs must use 'app_label.model:codename' format."
            )
        app_label, model = model_ref.split(".", 1)
        if not app_label or not model or not codename:
            raise ImproperlyConfigured(
                "Permission refs must use 'app_label.model:codename' format."
            )

    # ------------------------------------------------------------------
    # Value I/O
    # ------------------------------------------------------------------

    def value_from_datadict(self, data, files, name):
        raw = data.get(name)
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    @staticmethod
    def _is_standard_codename(codename, model_name):
        return codename in {f"{action}_{model_name}" for action in STANDARD_ACTIONS}

    @staticmethod
    def _standard_action(codename):
        return codename.split("_", 1)[0]

    @staticmethod
    def _parse_selected_permission_ids(value):
        """Normalize Django/widget values to selected permission ID integers."""
        if value is None or value == "":
            return set()

        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return set()

        if isinstance(value, (list, tuple)):
            selected = set()
            for item in value:
                if item is None:
                    continue
                try:
                    selected.add(int(item))
                except (TypeError, ValueError):
                    continue
            return selected

        return set()
