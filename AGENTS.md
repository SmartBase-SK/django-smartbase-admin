# Developer & AI Agent Reference

This document provides key patterns and gotchas for developers and AI assistants working with django-smartbase-admin.

---

## SBAdminField - List Display Columns

### Basic Usage

```python
from django_smartbase_admin.engine.field import SBAdminField

class MyModelAdmin(SBAdmin):
    sbadmin_list_display = (
        "field_name",  # Simple field reference
        SBAdminField(name="custom_field", ...),  # Custom field with options
    )
```

### Key Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | str | **Required**. Field identifier - can reference a model field OR an admin method |
| `title` | str | Column header label |
| `annotate` | Expression | Django ORM expression (F, Concat, Case, etc.) |
| `supporting_annotates` | dict | Additional annotations passed to admin method |
| `filter_field` | str | Field name for filtering (if different from display) |
| `filter_widget` | FilterWidget | Custom filter widget |
| `filter_disabled` | bool | Disable filtering for this field |
| `python_formatter` | callable | Format value: `(obj_id, value) -> formatted_value` |
| `list_visible` | bool | Show/hide column in list |

### Admin Methods (like Django admin)

Define a method on your admin class with the same name as the `SBAdminField.name`:

```python
class MyModelAdmin(SBAdmin):
    def formatted_status(self, obj_id, value, **additional_data):
        """
        Auto-discovered method (name matches SBAdminField.name).
        Receives: self, obj_id, annotated value, supporting_annotates as kwargs.
        """
        extra = additional_data.get("extra_data")
        return f"{value} - {extra}"
    
    sbadmin_list_display = (
        SBAdminField(
            name="formatted_status",  # Same as method name - auto-discovered
            annotate=F("status"),
            supporting_annotates={"extra_data": F("other_field")},
        ),
    )
```

### Why supporting_annotates?

The `supporting_annotates` approach provides two key performance benefits:

1. **Lazy loading**: When a column is hidden/deselected by the user, all its related annotations (including `supporting_annotates`) are automatically excluded from the query. This prevents unnecessary database computation.

2. **Shared queryset**: Filters operate on the same queryset as the list display. Annotations defined in `supporting_annotates` can be used for filtering while keeping the filtering and display logic cohesive.

### Annotation Name Conflicts

**CRITICAL**: Annotation keys in `supporting_annotates` must NOT match model field names!

```python
# ❌ BAD - 'created_at' conflicts with model field
supporting_annotates={"created_at": F("created_at")}

# ✅ GOOD - Use a different key name
supporting_annotates={"created_at_val": F("created_at")}
```

### Mixed Types in Expressions

When using `Concat`, `Coalesce`, or `Case`, always specify `output_field`:

```python
# ❌ BAD - FieldError: Expression contains mixed types
Concat(F("first_name"), Value(" "), F("last_name"))

# ✅ GOOD - Explicit output_field on all parts
from django.db.models import TextField

Concat(
    Coalesce(F("first_name"), Value(""), output_field=TextField()),
    Value(" ", output_field=TextField()),
    Coalesce(F("last_name"), Value(""), output_field=TextField()),
    output_field=TextField(),
)
```

---

## Configuration

### INSTALLED_APPS Setup

Add `django_smartbase_admin` and its dependencies to your `INSTALLED_APPS`. **Important**: `django_smartbase_admin` must be listed AFTER any apps that register model admins, to ensure those admins are registered before the configuration is initialized.

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "easy_thumbnails",
    "widget_tweaks",
    "ckeditor",
    "ckeditor_uploader",
    "myapp",  # Your app with model admins - BEFORE django_smartbase_admin
    "django_smartbase_admin",  # MUST be last (or after apps with model admins)
]
```

### Required Setup

1. **Settings**: `SB_ADMIN_CONFIGURATION = "myapp.sbadmin_config.SBAdminConfiguration"`
2. **URLs**: Include `sb_admin_site.urls`
3. **Config Class**: Implement `get_configuration_for_roles`

```python
from django_smartbase_admin.engine.configuration import SBAdminConfigurationBase, SBAdminRoleConfiguration
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView

_role_config = SBAdminRoleConfiguration(
    default_view=SBAdminMenuItem(view_id="dashboard"),
    menu_items=[
        SBAdminMenuItem(label="Dashboard", icon="All-application", view_id="dashboard"),
        SBAdminMenuItem(label="My Model", icon="icon-name", view_id="myapp_mymodel"),
    ],
    registered_views=[
        SBAdminDashboardView(widgets=[], title="Dashboard"),
    ],
)

class SBAdminConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        return _role_config
```

**Note**: Use `registered_views` with `SBAdminDashboardView` to register custom views. Model admin views (like `myapp_mymodel`) are automatically discovered from the admin site registry when `django_smartbase_admin` loads (which is why the INSTALLED_APPS ordering matters).

### Menu Item View IDs

Format: `{app_label}_{model_name}` (lowercase)

Example: `myapp.models.Product` → `view_id="myapp_product"`

### Global Queryset Filtering

Override `restrict_queryset` on `SBAdminRoleConfiguration` to apply global filters for specific models across all views. For reusable filtering logic, extract it to a separate module:

```python
# myapp/queryset_restrictions.py
from myapp.models import MyModel, RelatedModel

def apply_model_restrictions(qs):
    """Apply global queryset restrictions based on queryset's model."""
    if qs.model == MyModel:
        qs = qs.filter(status__in=["published", "draft"])
    elif qs.model == RelatedModel:
        qs = qs.filter(is_hidden=False)
    return qs
```

```python
# myapp/sbadmin_config.py
from django_smartbase_admin.engine.configuration import SBAdminConfigurationBase, SBAdminRoleConfiguration
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView

from myapp.queryset_restrictions import apply_model_restrictions

class MyRoleConfiguration(SBAdminRoleConfiguration):
    """Role configuration with queryset restrictions."""

    def restrict_queryset(self, qs, model, request, request_data, global_filter=True, global_filter_data_map=None):
        """Apply global queryset restrictions."""
        return apply_model_restrictions(qs)


_role_config = MyRoleConfiguration(
    default_view=SBAdminMenuItem(view_id="dashboard"),
    menu_items=[
        SBAdminMenuItem(label="Dashboard", icon="All-application", view_id="dashboard"),
        SBAdminMenuItem(label="My Model", icon="icon-name", view_id="myapp_mymodel"),
    ],
    registered_views=[
        SBAdminDashboardView(widgets=[], title="Dashboard"),
    ],
)


class SBAdminConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        return _role_config
```

**Key points:**
- Extract restriction logic to a separate module (e.g., `queryset_restrictions.py`) to avoid circular imports
- Use `qs.model` to check the model type - simpler than passing model as a separate parameter
- Override `restrict_queryset` on `SBAdminRoleConfiguration` subclass to call your restriction function
- Import `apply_model_restrictions` directly in filter widgets and subqueries: `apply_model_restrictions(Model.objects.all())`

---

## Filter Widgets

### Built-in Widgets

| Widget | Use Case |
|--------|----------|
| `StringFilterWidget` | Text fields |
| `BooleanFilterWidget` | Boolean fields |
| `DateFilterWidget` | Date/DateTime fields |
| `AutocompleteFilterWidget` | ForeignKey/M2M fields |
| `FromValuesAutocompleteWidget` | Filter from distinct values |
| `ChoiceFilterWidget` | Static choices |
| `MultipleChoiceFilterWidget` | Multiple selection |

### Custom Filter Widget Example

```python
from django_smartbase_admin.engine.filter_widgets import FromValuesAutocompleteWidget

class NonEmptyValuesFilter(FromValuesAutocompleteWidget):
    """Excludes empty/null values from filter choices."""
    
    def get_queryset(self, request=None):
        qs = super().get_queryset(request)
        return qs.exclude(**{f"{self.field.name}__exact": ""}).exclude(**{f"{self.field.name}__isnull": True})
```

### Complex Filter with filter_query_lambda

For filtering via related models (e.g., filtering parent by child relationship), use `AutocompleteFilterWidget` with `filter_query_lambda`:

```python
from django.db.models import Q
from django_smartbase_admin.engine.filter_widgets import AutocompleteFilterWidget

class RelatedModelFilterWidget(AutocompleteFilterWidget):
    """Filter parent model by selecting related child model items."""

    def __init__(self):
        super().__init__(
            model=ChildModel,
            multiselect=True,
            value_field="id",
            label_lambda=lambda request, item: item.name,
            filter_query_lambda=self._filter_by_related,
        )

    def _filter_by_related(self, request, selected_ids):
        if not selected_ids:
            return Q()
        # Query the junction/relation table to find parent IDs
        parent_ids = RelationModel.objects.filter(
            child_id__in=selected_ids
        ).values_list("parent_id", flat=True)
        return Q(id__in=parent_ids)

    def get_queryset(self, request=None):
        return ChildModel.objects.filter(is_active=True).order_by("name")
```

Use in SBAdminField:

```python
SBAdminField(
    name="display_field",
    title="Display",
    annotate=Value("", output_field=TextField()),
    filter_field="relation__child",  # For list_filter reference
    filter_widget=RelatedModelFilterWidget(),
),
```

### Filter-Only Fields (No Column)

To add a filter that doesn't appear as a visible column, use `list_visible=False`:

```python
sbadmin_list_display = (
    # Visible column with filter
    SBAdminField(
        name="categories_display",
        title="Categories",
        filter_field="items__category",
        filter_widget=CategoryFilterWidget(),
    ),
    # Filter only - no column shown
    SBAdminField(
        name="labels_filter",
        title="Labels",
        annotate=Value("", output_field=TextField()),
        filter_field="items__label",
        filter_widget=LabelFilterWidget(),
        list_visible=False,  # Hidden from columns, visible in filter panel
    ),
)

list_filter = (
    "items__category",  # Shows in filter panel
    "items__label",     # Shows in filter panel (even though column is hidden)
)
```

This is useful when you want to filter by related data that doesn't need its own column display.

---

## Admin Registration

```python
from django.contrib import admin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.admin.admin_base import SBAdmin

@admin.register(MyModel, site=sb_admin_site)
class MyModelAdmin(SBAdmin):
    model = MyModel
    sbadmin_list_display = (...)
    list_filter = (...)
    search_fields = (...)
```

### Default Visible Filters

`list_filter` controls which column filters are visible by default. Include field names or the `filter_field` value from `SBAdminField`:

```python
sbadmin_list_display = (
    "username",
    SBAdminField(name="status", filter_field="status"),
    SBAdminField(name="manager_name", filter_field="manager__email"),  # Related field
    SBAdminField(name="computed", filter_disabled=True),  # No filter
)

# list_filter should match filter_field values (not SBAdminField names)
list_filter = (
    "username",
    "status", 
    "manager__email",  # Use filter_field value for related lookups
    # "computed" excluded - has filter_disabled=True
)

---

## Selection Actions (Bulk Actions)

Add custom actions that operate on selected rows in the list view.

### Using SBAdminFormViewAction with Modal

For actions that need user input (like selecting options), use `SBAdminFormViewAction` with `ListActionModalView`:

```python
from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from django_smartbase_admin.admin.admin_base import SBAdminBaseFormInit
from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget
from django_smartbase_admin.engine.actions import SBAdminFormViewAction
from django_smartbase_admin.engine.modal_view import ListActionModalView

from myapp.models import RelatedModel


class MyActionForm(SBAdminBaseFormInit, forms.Form):
    """Form with SBAdminBaseFormInit mixin for modal integration."""
    option = forms.ChoiceField(choices=[("a", "Option A"), ("b", "Option B")])
    # For autocomplete multiselect - model restrictions applied automatically via restrict_queryset
    items = forms.ModelMultipleChoiceField(
        label=_("Items"),
        queryset=RelatedModel.objects.all(),
        required=False,
        widget=SBAdminAutocompleteWidget(
            model=RelatedModel,
            multiselect=True,
            label_lambda=lambda request, item: str(item),
            # filter_search_lambda returns Q object for additional filtering
            # Use for dependent dropdowns (forward) or custom search filtering
            filter_search_lambda=lambda request, search_term, forward_data: Q(category=forward_data.get("category")),
        ),
    )


class MyActionView(ListActionModalView):
    form_class = MyActionForm
    modal_title = _("My Action")

    def process_form_valid_list_selection_queryset(self, request, form, selection_queryset):
        """Called with the selected rows queryset after form validation."""
        option = form.cleaned_data["option"]
        for obj in selection_queryset:
            # Process each selected object
            pass


class MyModelAdmin(SBAdmin):
    def get_sbadmin_list_selection_actions(self, request):
        """Override to define custom selection actions."""
        return [
            SBAdminFormViewAction(
                target_view=MyActionView,
                title=_("My Action"),
                view=self,
                action_id="my_action",
                open_in_modal=True,
            ),
        ]
```

### Key Points

- Override `get_sbadmin_list_selection_actions(request)` to return custom actions
- Use `SBAdminFormViewAction` with `open_in_modal=True` for modal dialogs
- Extend `ListActionModalView` and implement `process_form_valid_list_selection_queryset`
- Forms should extend `SBAdminBaseFormInit` mixin (from `django_smartbase_admin.admin.admin_base`)
- For autocomplete multiselect: use `SBAdminAutocompleteWidget` with `ModelMultipleChoiceField` (model restrictions applied automatically via `restrict_queryset`)
- `selection_queryset` contains all selected rows, already filtered by user selection
- Default actions include "Export Selected" and "Delete Selected"

### Modal Success Notifications and Error Handling

Django SmartBase Admin uses Django's messages framework with HTMX out-of-band swaps for notifications. When handling success/error in modal views:

**Error handling** - Display errors in the modal form:
```python
class MyActionView(ListActionModalView):
    def process_form_valid(self, request, form):
        try:
            return super().process_form_valid(request, form)
        except MyCustomError as e:
            form.add_error(None, str(e))  # Add as non-field error
            return self.form_invalid(form)  # Re-render modal with error
```

The modal template (`sb_admin/partials/modal/modal_content.html`) automatically displays `form.errors` and `form.non_field_errors` in a styled alert box.

**Success notifications** - Show toast notification and close modal:
```python
from django.contrib import messages
from django.http import HttpResponse
from django.template.loader import render_to_string
from django_htmx.http import trigger_client_event
from django_smartbase_admin.engine.const import TABLE_RELOAD_DATA_EVENT_NAME

class MyActionView(ListActionModalView):
    success_message = _("Action completed successfully.")

    def process_form_valid(self, request, form):
        try:
            selection_queryset = self.get_selection_queryset(request, form)
            self.process_form_valid_list_selection_queryset(request, form, selection_queryset)
        except MyCustomError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)

        # Add success message and render notifications template
        messages.success(request, self.success_message)
        notifications_html = render_to_string(
            "sb_admin/includes/notifications.html",
            {"messages": messages.get_messages(request)},
            request=request,
        )

        # Return response with notifications (OOB swap) and client events
        response = HttpResponse(notifications_html)
        trigger_client_event(response, "hideModal", {})
        trigger_client_event(response, TABLE_RELOAD_DATA_EVENT_NAME, {})
        return response
```

**How it works:**
- `notifications.html` has `hx-swap-oob="beforeend"` - HTMX appends it to the notification container
- Success alerts auto-dismiss after 5 seconds (`remove-me="5s"` attribute)
- Message levels: `messages.success()`, `messages.warning()`, `messages.error()` map to different alert styles

---

## Field Formatters

Built-in formatters for common display patterns in `django_smartbase_admin.engine.field_formatter`:

```python
from django_smartbase_admin.engine.field_formatter import (
    array_badge_formatter,                  # Display list as horizontal badges
    newline_separated_array_badge_formatter, # Display list as vertical badges (one per line)
    boolean_formatter,                      # Yes/No badges
    datetime_formatter,                     # Localized datetime
    datetime_formatter_with_format,         # Custom date/time format
    link_formatter,                         # Clickable URL
    rich_text_formatter,                    # HTML content with max-width
    format_array,                           # Custom badge formatting with BadgeType
)
```

### Array Badge Formatters

Display lists as styled badge pills (great for tags, queues, categories):

```python
from django_smartbase_admin.engine.field_formatter import (
    array_badge_formatter,                   # Horizontal: [Tag1] [Tag2] [Tag3]
    newline_separated_array_badge_formatter, # Vertical: [Tag1]
                                             #           [Tag2]
                                             #           [Tag3]
)

class MyAdmin(SBAdmin):
    def tags_display(self, obj_id, value, **additional_data):
        tags = ["Tag1", "Tag2", "Tag3"]
        # Use newline_separated_array_badge_formatter for vertical layout
        return newline_separated_array_badge_formatter(obj_id, tags)
    
    sbadmin_list_display = (
        SBAdminField(
            name="tags_display",
            title="Tags",
            annotate=Value("", output_field=TextField()),
            filter_disabled=True,
        ),
    )
```

### Badge Types

Use `format_array` directly for custom badge colors:

```python
from django_smartbase_admin.engine.field_formatter import format_array, BadgeType

# BadgeType options: SUCCESS (green), WARNING (yellow), ERROR (red), NOTICE (default)
format_array(["item1", "item2"], badge_type=BadgeType.SUCCESS)
```

---

## Performance Optimization

### Preventing N+1 Queries with Subqueries

Use `Subquery` and `ArrayAgg` in `supporting_annotates` to fetch related data in a single query instead of per-row queries:

```python
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import DateTimeField, OuterRef, Q, Subquery, TextField, Value
from django.db.models.functions import Coalesce, Concat

# Subquery for scalar value (e.g., get related datetime field)
def get_latest_event_subquery() -> Subquery:
    return Subquery(
        Event.objects.filter(user_id=OuterRef("pk"))
        .order_by("-created_at")
        .values("created_at")[:1],
        output_field=DateTimeField(),
    )

# Subquery for array aggregation (e.g., get list of related names)
def get_tag_names_subquery() -> Subquery:
    return Subquery(
        UserTag.objects.filter(user_id=OuterRef("pk"))
        .values("user_id")
        .annotate(names=ArrayAgg("tag__name", distinct=True))
        .values("names")[:1]
    )

class MyAdmin(SBAdmin):
    def event_time_display(self, obj_id, value, **additional_data):
        event_time = additional_data.get("latest_event_val")
        return event_time.strftime("%Y-%m-%d") if event_time else "-"
    
    def tags_display(self, obj_id, value, **additional_data):
        tag_names = additional_data.get("tag_names_arr") or []
        if not tag_names:
            return ""
        badges = "".join(f'<span class="badge">{name}</span>' for name in tag_names if name)
        return mark_safe(badges)
    
    sbadmin_list_display = (
        SBAdminField(
            name="event_time_display",
            title="Last Event",
            annotate=Value("", output_field=TextField()),
            supporting_annotates={
                "latest_event_val": get_latest_event_subquery(),
            },
            filter_disabled=True,
        ),
        SBAdminField(
            name="tags_display",
            title="Tags",
            annotate=Value("", output_field=TextField()),
            supporting_annotates={
                "tag_names_arr": get_tag_names_subquery(),
            },
            filter_disabled=True,
        ),
    )
```

**Key patterns:**
- Use `OuterRef("pk")` to reference the parent model's primary key
- Add `[:1]` to limit subquery to single result for scalar values
- Use `ArrayAgg` from `django.contrib.postgres.aggregates` for PostgreSQL array aggregation
- Always specify `output_field` on Subquery for type hints

### Pagination

Control initial rows displayed with `list_per_page`:

```python
class MyAdmin(SBAdmin):
    list_per_page = 20  # Show 20 rows initially
```

---

## Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| "Menu item is missing view X" | `view_id` doesn't match registered admin | Use format `{app_label}_{model_name}` |
| "The annotation 'X' conflicts with a field" | `supporting_annotates` key matches model field | Rename annotation key |
| "Expression contains mixed types" | Missing `output_field` in expression | Add `output_field=TextField()` to all parts |
| "relation 'django_smartbase_admin_X' does not exist" | Missing migrations | Run `python manage.py migrate` |

---

## Logo Customization

Override default logo by placing files in your static directory:
- `static/sb_admin/images/logo.svg` - Light mode
- `static/sb_admin/images/logo_light.svg` - Dark mode

