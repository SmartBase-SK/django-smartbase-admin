# Developer & AI Agent Reference

This document provides key patterns and gotchas for developers and AI assistants working with django-smartbase-admin.

---

## Table of Contents

| Section | What it covers |
|---------|----------------|
| [Demo Schema Reference](#demo-schema-reference) | Models used in all examples (Article, Category, Tag, Author, Comment) |
| [SBAdminField](#sbadminfield---list-display-columns) | Defining list columns, annotations, `supporting_annotates`, admin methods |
| [Configuration](#configuration) | `INSTALLED_APPS`, role config, menu items, queryset restrictions |
| [Filter Widgets](#filter-widgets) | Built-in widgets, custom filters, `filter_query_lambda` for M2M filtering |
| [Admin Registration](#admin-registration) | `@admin.register` with `sb_admin_site`, `list_filter` setup |
| [Selection Actions](#selection-actions-bulk-actions) | Modal forms for bulk operations, `ListActionModalView`, success/error handling |
| [Field Formatters](#field-formatters) | Badge formatters, `array_badge_formatter`, `BadgeType` options |
| [Performance Optimization](#performance-optimization) | `Subquery` patterns, `ArrayAgg`, avoiding N+1 queries |
| [Common Errors](#common-errors) | Frequent errors and solutions |
| [Inlines](#inlines) | `SBAdminTableInline`, `SBAdminStackedInline` for related models |
| [Global Autocomplete Widget Customization](#global-autocomplete-widget-customization) | `label_lambda`, `search_query_lambda`, dependent dropdowns, subclassing for computed values |
| [Pre-filtered List Views](#pre-filtered-list-views-sbadmin_list_view_config) | Tab-based filtered views with `sbadmin_list_view_config` |
| [Logo Customization](#logo-customization) | Override logo via static files |
| [Contributing to This Document](#contributing-to-this-document) | Guidelines for adding new sections and examples |

**Quick lookup:**
- **Adding a column?** → [SBAdminField](#sbadminfield---list-display-columns)
- **Filtering by related model?** → [Filter Widgets](#filter-widgets) (filter_query_lambda)
- **Bulk action with modal?** → [Selection Actions](#selection-actions-bulk-actions)
- **N+1 query issues?** → [Performance Optimization](#performance-optimization)
- **Autocomplete customization?** → [Global Autocomplete Widget Customization](#global-autocomplete-widget-customization)

---

## Demo Schema Reference

Examples throughout this document use a consistent CMS-style schema:

```python
# blog/models.py
class Author(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    is_active = models.BooleanField(default=True)

class Category(models.Model):
    name = models.CharField(max_length=100)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE)

class Tag(models.Model):
    name = models.CharField(max_length=50)

class Article(models.Model):
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20)  # draft, published, archived
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

class ArticleTag(models.Model):
    """M2M junction table for Article <-> Tag."""
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="article_tags")
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE)

class Comment(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="comments")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
```

---

## SBAdminField - List Display Columns

### Basic Usage

```python
from django_smartbase_admin.engine.field import SBAdminField

class ArticleAdmin(SBAdmin):
    sbadmin_list_display = (
        "title",  # Simple field reference
        SBAdminField(name="status_display", ...),  # Custom field with options
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
class ArticleAdmin(SBAdmin):
    def status_display(self, obj_id, value, **additional_data):
        """
        Auto-discovered method (name matches SBAdminField.name).
        Receives: self, obj_id, annotated value, supporting_annotates as kwargs.
        """
        category_name = additional_data.get("category_name_val")
        return f"{value} - {category_name}"
    
    sbadmin_list_display = (
        SBAdminField(
            name="status_display",  # Same as method name - auto-discovered
            annotate=F("status"),
            supporting_annotates={"category_name_val": F("category__name")},
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

### supporting_annotates Requires Expressions

**CRITICAL**: Values in `supporting_annotates` must be Django ORM expressions (like `F()`), NOT plain strings!

```python
# ❌ BAD - Causes "QuerySet.annotate() received non-expression(s)" error
supporting_annotates={
    "author_name": "author__name",
    "category_name": "category__name",
}

# ✅ GOOD - Use F() expressions
from django.db.models import F

supporting_annotates={
    "author_name_val": F("author__name"),
    "category_name_val": F("category__name"),
}
```

This applies even when referencing simple model fields - always wrap field names in `F()`.

### Mixed Types in Expressions

When using `Concat`, `Coalesce`, or `Case`, always specify `output_field`:

```python
# ❌ BAD - FieldError: Expression contains mixed types
Concat(F("author__name"), Value(" <"), F("author__email"), Value(">"))

# ✅ GOOD - Explicit output_field on all parts
from django.db.models import TextField

Concat(
    Coalesce(F("author__name"), Value(""), output_field=TextField()),
    Value(" <", output_field=TextField()),
    Coalesce(F("author__email"), Value(""), output_field=TextField()),
    Value(">", output_field=TextField()),
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
    "blog",  # Your app with model admins - BEFORE django_smartbase_admin
    "django_smartbase_admin",  # MUST be last (or after apps with model admins)
]
```

### Required Setup

1. **Settings**: `SB_ADMIN_CONFIGURATION = "blog.sbadmin_config.SBAdminConfiguration"`
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
        SBAdminMenuItem(label="Articles", icon="Box", view_id="blog_article"),
    ],
    registered_views=[
        SBAdminDashboardView(widgets=[], title="Dashboard"),
    ],
)

class SBAdminConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        return _role_config
```

**Note**: Use `registered_views` with `SBAdminDashboardView` to register custom views. Model admin views (like `blog_article`) are automatically discovered from the admin site registry when `django_smartbase_admin` loads (which is why the INSTALLED_APPS ordering matters).

### Menu Item View IDs

Format: `{app_label}_{model_name}` (lowercase)

Example: `blog.models.Article` → `view_id="blog_article"`

### Menu Item Icons

Icons are SVG sprites from the `static/sb_admin/sprites/sb_admin/` directory. Use the filename without extension:

**Available Icons:**
```
Accept-email, Ad-product, Add-one, Add-picture, Add-three, Aiming, All-application,
Alphabetical-sorting, Alphabetical-sorting-two, Application, Application-menu,
Application-two, Arrow-circle-down, Arrow-circle-left, Arrow-circle-right,
Arrow-circle-up, At-sign, Attention, Back-one, Bank-card, Bank-card-one, Bolt-one,
Bookmark, Box, Calendar, Camera, Caution, Check, Check-correct, Check-one,
Check-one-filled, Check-small, Close, Close-one, Close-small, Column,
Corner-up-left, Corner-up-right, Cut, Cylinder, Delete, Delete-two, Double-down,
Double-left, Double-right, Double-up, Down, Down-c, Down-small, Download,
Download-one, Drag, Edit, Electric-drill, Excel-one, Export, Figma-component,
Filter, Find, Fire-extinguisher, Gas, Go-ahead, Go-on, Hamburger-button,
Headset-one, Help, Home, Id-card-h, Info, Left, Left-c, Left-small,
Left-small-down, Left-small-up, Lightning, Lightning-fill, Like, Link-two,
List-checkbox, Lock, Login, Logout, Magic, Magic-wand, Mail, Mail-download,
Mail-open, Message-emoji, Message-one, Minus, Minus-the-top, Moon, More,
More-one, More-three, More-two, Paperclip, Parallel-gateway, People-top-card,
Percentage, Phone-telephone, Picture-one, Pin, Pin Filled, Plus, Preview-close,
Preview-close-one, Preview-open, Printer, Pull, Pushpin, Reduce-one, Refresh-one,
Return, Rewora, Rewora Filled, Right, Right-c, Right-small, Right-small-down,
Right-small-up, Save, Search, Send-email, Setting-config, Setting-two, Shop,
Shopping, Shopping-bag, Shopping-cart-one, Sort, Sort-amount-down, Sort-amount-up,
Sort-one, Sort-three, Sort Alt, Star, Success, Sun-one, Switch, Table-report,
Tag, Tag-one, Time, Tips-one, To-top, Transfer-data, Translate, Translation,
Triangle-round-rectangle, Truck, Undo, Unlock, Up, Up-c, Up-small, Upload,
Upload-one, User-business, View-grid-list, Write, Zoom-in, Zoom-out
```

Example:
```python
SBAdminMenuItem(label="Dashboard", icon="All-application", view_id="dashboard"),
SBAdminMenuItem(label="Authors", icon="User-business", view_id="blog_author"),
SBAdminMenuItem(label="Articles", icon="Box", view_id="blog_article"),
SBAdminMenuItem(label="Settings", icon="Setting-config", view_id="blog_settings"),
```

### Nested Menu Items (sub_items)

Use `sub_items` to create nested/dropdown menu sections:

```python
_role_config = SBAdminRoleConfiguration(
    default_view=SBAdminMenuItem(view_id="dashboard"),
    menu_items=[
        SBAdminMenuItem(label="Dashboard", icon="All-application", view_id="dashboard"),
        SBAdminMenuItem(
            label="Content",
            icon="Box",
            sub_items=[
                SBAdminMenuItem(label="Articles", view_id="blog_article"),
                SBAdminMenuItem(label="Categories", view_id="blog_category"),
                SBAdminMenuItem(label="Tags", view_id="blog_tag"),
            ],
        ),
        SBAdminMenuItem(
            label="People",
            icon="User-business",
            sub_items=[
                SBAdminMenuItem(label="Authors", view_id="blog_author"),
                SBAdminMenuItem(label="Comments", view_id="blog_comment"),
            ],
        ),
    ],
    registered_views=[
        SBAdminDashboardView(widgets=[], title="Dashboard"),
    ],
)
```

**Key points:**
- Parent menu items with `sub_items` don't need a `view_id` (they act as dropdown containers)
- Child items in `sub_items` typically don't need icons (parent icon is shown)
- Nested items automatically highlight when their view is active

### Global Queryset Filtering

Override `restrict_queryset` on `SBAdminRoleConfiguration` to apply global filters for specific models across all views. For reusable filtering logic, extract it to a separate module:

```python
# blog/queryset_restrictions.py
from blog.models import Article, Author

def apply_model_restrictions(qs):
    """Apply global queryset restrictions based on queryset's model."""
    if qs.model == Article:
        qs = qs.filter(status__in=["published", "draft"])
    elif qs.model == Author:
        qs = qs.filter(is_active=True)
    return qs
```

```python
# blog/sbadmin_config.py
from django_smartbase_admin.engine.configuration import SBAdminConfigurationBase, SBAdminRoleConfiguration
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView

from blog.queryset_restrictions import apply_model_restrictions

class BlogRoleConfiguration(SBAdminRoleConfiguration):
    """Role configuration with queryset restrictions."""

    def restrict_queryset(self, qs, model, request, request_data, global_filter=True, global_filter_data_map=None):
        """Apply global queryset restrictions."""
        return apply_model_restrictions(qs)


_role_config = BlogRoleConfiguration(
    default_view=SBAdminMenuItem(view_id="dashboard"),
    menu_items=[
        SBAdminMenuItem(label="Dashboard", icon="All-application", view_id="dashboard"),
        SBAdminMenuItem(label="Articles", icon="Box", view_id="blog_article"),
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
- Import `apply_model_restrictions` directly in filter widgets and subqueries: `apply_model_restrictions(Article.objects.all())`

### User-Based Queryset Filtering (Thread-Local Request)

For user-based filtering (e.g., restricting data by user permissions or tenant), use `SBAdminThreadLocalService` to access the current request when it's not passed directly. This is useful when `apply_model_restrictions` is called from filter widgets or subqueries where request isn't available as a parameter.

```python
# blog/queryset_restrictions.py
from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService

from blog.models import Article, Author


def _get_current_request(request=None):
    """Get request from parameter or thread-local storage."""
    if request is not None:
        return request
    try:
        return SBAdminThreadLocalService.get_request()
    except LookupError:
        return None


def apply_model_restrictions(qs, request=None):
    """Apply global queryset restrictions based on queryset's model.

    For models requiring user-based filtering:
    - admin users: see all records
    - restricted users: see only records matching their allowed scope
    - no request available: return empty queryset (fail-safe)
    """
    if qs.model == Article:
        current_request = _get_current_request(request)
        if current_request is None:
            return qs.none()  # Fail-safe: no access without request

        user = getattr(current_request, "user", None)
        if user is None:
            return qs.none()  # Fail-safe: no access without user

        qs = qs.filter(status__in=["published", "draft"])
        # Example: filter by user's allowed categories
        allowed_categories = getattr(user, "allowed_categories", None)
        if allowed_categories is not None:
            qs = qs.filter(category__in=allowed_categories)
    elif qs.model == Author:
        qs = qs.filter(is_active=True).order_by("name")
    return qs
```

```python
# blog/sbadmin_config.py
class BlogRoleConfiguration(SBAdminRoleConfiguration):
    def restrict_queryset(self, qs, model, request, request_data, global_filter=True, global_filter_data_map=None):
        """Apply global queryset restrictions, passing request for user-based filtering."""
        return apply_model_restrictions(qs, request=request)
```

**Key points:**
- `SBAdminThreadLocalService.get_request()` returns the current request stored in thread-local/context-var storage
- Raises `LookupError` if no request is set (e.g., outside of a request context)
- **Fail-safe pattern**: Return `qs.none()` when request or user is unavailable to prevent data leakage
- Pass `request` explicitly from `restrict_queryset` when available; the function falls back to thread-local when called from filter widgets or subqueries
- User object should have properties like `allowed_categories` that return filtering criteria (or `None` for full access)

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

For filtering via related models (e.g., filtering articles by selecting tags), use `AutocompleteFilterWidget` with `filter_query_lambda`:

```python
from django.db.models import Q
from django_smartbase_admin.engine.filter_widgets import AutocompleteFilterWidget

from blog.models import Tag, ArticleTag

class TagFilterWidget(AutocompleteFilterWidget):
    """Filter articles by selecting tags."""

    def __init__(self):
        super().__init__(
            model=Tag,
            multiselect=True,
            value_field="id",
            label_lambda=lambda request, item: item.name,
            filter_query_lambda=self._filter_by_tags,
        )

    def _filter_by_tags(self, request, selected_ids):
        if not selected_ids:
            return Q()
        # Query the junction table to find article IDs
        article_ids = ArticleTag.objects.filter(
            tag_id__in=selected_ids
        ).values_list("article_id", flat=True)
        return Q(id__in=article_ids)

    def get_queryset(self, request=None):
        return Tag.objects.all().order_by("name")
```

Use in SBAdminField:

```python
SBAdminField(
    name="tags_display",
    title="Tags",
    annotate=Value("", output_field=TextField()),
    filter_field="article_tags__tag",
    filter_widget=TagFilterWidget(),
),
```

### Filter Widget Behavior Parameters

Control filter dropdown behavior with `close_dropdown_on_change` and `allow_clear`:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `close_dropdown_on_change` | bool | `False` | If `True`, the filter dropdown closes automatically after the filter value changes. Useful for single-step filters like boolean or simple text inputs. Set to `False` for widgets where users typically make multiple changes before closing (e.g., multiselect autocomplete). |
| `allow_clear` | bool | `True` | If `True`, shows a "Clear" button in the filter dropdown to reset the filter value. Set to `False` to hide the clear button. |

**Examples:**

```python
from django_smartbase_admin.engine.filter_widgets import AutocompleteFilterWidget

# Single-step filter - closes dropdown after selection
class StatusFilterWidget(AutocompleteFilterWidget):
    def __init__(self):
        super().__init__(
            model=Article,
            multiselect=False,
            close_dropdown_on_change=True,  # Close after selecting status
            allow_clear=True,
        )

# Multi-step filter - keep dropdown open for multiple selections
class TagFilterWidget(AutocompleteFilterWidget):
    def __init__(self):
        super().__init__(
            model=Tag,
            multiselect=True,
            close_dropdown_on_change=False,  # Keep open for multiple tag selections
            allow_clear=True,
        )

# Filter without clear button
class RequiredCategoryFilterWidget(AutocompleteFilterWidget):
    def __init__(self):
        super().__init__(
            model=Category,
            multiselect=False,
            close_dropdown_on_change=True,
            allow_clear=False,  # Hide clear button - category is required
        )
```

**Key points:**
- Built-in widgets like `StringFilterWidget` and `BooleanFilterWidget` default to `close_dropdown_on_change=True` for better UX
- `AutocompleteFilterWidget` defaults to `close_dropdown_on_change=False` to allow multiple selections
- The clear button is automatically hidden for required form fields (controlled by `form_field.required`)

### Filter-Only Fields (No Column)

To add a filter that doesn't appear as a visible column, use `list_visible=False`:

```python
sbadmin_list_display = (
    # Visible column with filter
    SBAdminField(
        name="category_display",
        title="Category",
        filter_field="category",
        filter_widget=CategoryFilterWidget(),
    ),
    # Filter only - no column shown
    SBAdminField(
        name="author_filter",
        title="Author",
        annotate=Value("", output_field=TextField()),
        filter_field="author",
        filter_widget=AuthorFilterWidget(),
        list_visible=False,  # Hidden from columns, visible in filter panel
    ),
)

list_filter = (
    "category",  # Shows in filter panel
    "author",    # Shows in filter panel (even though column is hidden)
)
```

This is useful when you want to filter by related data that doesn't need its own column display.

---

## Admin Registration

```python
from django.contrib import admin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.admin.admin_base import SBAdmin

from blog.models import Article

@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    model = Article
    sbadmin_list_display = (...)
    list_filter = (...)
    search_fields = (...)
```

### Default Visible Filters

`list_filter` controls which column filters are visible by default. Include field names or the `filter_field` value from `SBAdminField`:

```python
sbadmin_list_display = (
    "title",
    SBAdminField(name="status", filter_field="status"),
    SBAdminField(name="author_name", filter_field="author__email"),  # Related field
    SBAdminField(name="comment_count", filter_disabled=True),  # No filter
)

# list_filter should match filter_field values (not SBAdminField names)
list_filter = (
    "title",
    "status", 
    "author__email",  # Use filter_field value for related lookups
    # "comment_count" excluded - has filter_disabled=True
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

from blog.models import Category


class AssignCategoryForm(SBAdminBaseFormInit, forms.Form):
    """Form with SBAdminBaseFormInit mixin for modal integration."""
    category = forms.ModelChoiceField(
        label=_("Category"),
        queryset=Category.objects.all(),
        widget=SBAdminAutocompleteWidget(
            model=Category,
            multiselect=False,
            label_lambda=lambda request, item: item.name,
        ),
    )


class AssignCategoryView(ListActionModalView):
    form_class = AssignCategoryForm
    modal_title = _("Assign Category")

    def process_form_valid_list_selection_queryset(self, request, form, selection_queryset):
        """Called with the selected rows queryset after form validation."""
        category = form.cleaned_data["category"]
        selection_queryset.update(category=category)


class ArticleAdmin(SBAdmin):
    def get_sbadmin_list_selection_actions(self, request):
        """Override to define custom selection actions."""
        return [
            SBAdminFormViewAction(
                target_view=AssignCategoryView,
                title=_("Assign Category"),
                view=self,
                action_id="assign_category",
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
class AssignCategoryView(ListActionModalView):
    def process_form_valid(self, request, form):
        try:
            return super().process_form_valid(request, form)
        except ValidationError as e:
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

class AssignCategoryView(ListActionModalView):
    success_message = _("Category assigned successfully.")

    def process_form_valid(self, request, form):
        try:
            selection_queryset = self.get_selection_queryset(request, form)
            self.process_form_valid_list_selection_queryset(request, form, selection_queryset)
        except ValidationError as e:
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

Display lists as styled badge pills (great for tags, categories):

```python
from django_smartbase_admin.engine.field_formatter import (
    array_badge_formatter,                   # Horizontal: [Tag1] [Tag2] [Tag3]
    newline_separated_array_badge_formatter, # Vertical: [Tag1]
                                             #           [Tag2]
                                             #           [Tag3]
)

class ArticleAdmin(SBAdmin):
    def tags_display(self, obj_id, value, **additional_data):
        tag_names = additional_data.get("tag_names_arr") or []
        return newline_separated_array_badge_formatter(obj_id, tag_names)
    
    sbadmin_list_display = (
        SBAdminField(
            name="tags_display",
            title="Tags",
            annotate=Value("", output_field=TextField()),
            supporting_annotates={"tag_names_arr": get_tag_names_subquery()},
            filter_disabled=True,
        ),
    )
```

### Badge Types

Use `format_array` directly for custom badge colors:

```python
from django_smartbase_admin.engine.field_formatter import format_array, BadgeType

# BadgeType options: SUCCESS (green), WARNING (yellow), ERROR (red), NOTICE (default)
format_array(["Published", "Featured"], badge_type=BadgeType.SUCCESS)
```

---

## Performance Optimization

### Preventing N+1 Queries with Subqueries

Use `Subquery` and `ArrayAgg` in `supporting_annotates` to fetch related data in a single query instead of per-row queries:

```python
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import DateTimeField, OuterRef, Subquery, TextField, Value
from django.db.models.functions import Coalesce

from blog.models import ArticleTag, Comment

# Subquery for scalar value (e.g., get latest comment time)
def get_latest_comment_subquery() -> Subquery:
    return Subquery(
        Comment.objects.filter(article_id=OuterRef("pk"))
        .order_by("-created_at")
        .values("created_at")[:1],
        output_field=DateTimeField(),
    )

# Subquery for array aggregation (e.g., get list of tag names)
def get_tag_names_subquery() -> Subquery:
    return Subquery(
        ArticleTag.objects.filter(article_id=OuterRef("pk"))
        .values("article_id")
        .annotate(names=ArrayAgg("tag__name", distinct=True))
        .values("names")[:1]
    )

class ArticleAdmin(SBAdmin):
    def latest_comment_display(self, obj_id, value, **additional_data):
        comment_time = additional_data.get("latest_comment_val")
        return comment_time.strftime("%Y-%m-%d") if comment_time else "-"
    
    def tags_display(self, obj_id, value, **additional_data):
        tag_names = additional_data.get("tag_names_arr") or []
        if not tag_names:
            return ""
        badges = "".join(f'<span class="badge">{name}</span>' for name in tag_names if name)
        return mark_safe(badges)
    
    sbadmin_list_display = (
        SBAdminField(
            name="latest_comment_display",
            title="Last Comment",
            annotate=Value("", output_field=TextField()),
            supporting_annotates={
                "latest_comment_val": get_latest_comment_subquery(),
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
class ArticleAdmin(SBAdmin):
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

## Inlines

Use `SBAdminTableInline` instead of Django's `admin.TabularInline` for inlines in SBAdmin. This provides automatic autocomplete widgets for FK fields.

```python
from django_smartbase_admin.admin.admin_base import SBAdminTableInline

from blog.models import ArticleTag

class ArticleTagInline(SBAdminTableInline):
    model = ArticleTag
    extra = 0
    verbose_name = _("Tag")
    verbose_name_plural = _("Tags")

@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    model = Article
    inlines = [ArticleTagInline]
```

**Available inline classes:**
- `SBAdminTableInline` - Tabular layout (like `TabularInline`)
- `SBAdminStackedInline` - Stacked layout (like `StackedInline`)
- `SBAdminGenericTableInline` - For GenericForeignKey relations
- `SBAdminGenericStackedInline` - Stacked GenericForeignKey

---

## Global Autocomplete Widget Customization

Override `get_autocomplete_widget` in `SBAdminConfiguration` to customize autocomplete widgets globally. This applies to all auto-generated admin form fields including inlines.

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | Model class | **Required**. The Django model to query |
| `multiselect` | bool | Allow multiple selections (default: `True`) |
| `label_lambda` | callable | `(request, item) -> str` - Format how items appear in dropdown |
| `value_lambda` | callable | `(request, item) -> any` - Extract value from item (default: primary key) |
| `value_field` | str | Field name to use as value (alternative to `value_lambda`) |
| `search_query_lambda` | callable | `(request, qs, model, search_term, lang_code) -> QuerySet` - Define which fields to search. Default searches all CharField/TextField |
| `filter_search_lambda` | callable | `(request, search_term, forward_data) -> Q` - Pre-filter queryset before search. Use for dependent dropdowns with `forward` |
| `filter_query_lambda` | callable | `(request, selected_values) -> Q` - How selected values filter the main list (for filter widgets only) |
| `forward` | list[str] | Field names to forward to `filter_search_lambda` for dependent dropdowns |
| `allow_add` | bool | Allow creating new items inline (default: `False`, not supported with multiselect) |
| `create_value_field` | str | When `allow_add=True`, create a new model instance using the typed value as this field (e.g. `"name"`). Required to enable creation. |
| `forward_to_create` | list[str] | When creating a new value, also copy selected `forward` fields into the new object (useful for dependent dropdowns / setting FK like `parent`). |
| `hide_clear_button` | bool | Hide the clear/reset button (default: `False`) |

### Lambda Signatures

```python
# label_lambda - Format display label
def author_label(request, item) -> str:
    return f"{item.name} <{item.email}>"

# value_lambda - Extract value (default uses primary key)
def author_value(request, item) -> any:
    return item.pk

# search_query_lambda - Define searchable fields
def author_search(request, qs, model, search_term, language_code) -> QuerySet:
    if not search_term:
        return qs
    return qs.filter(Q(name__icontains=search_term) | Q(email__icontains=search_term))

# filter_search_lambda - Pre-filter based on forward data (dependent dropdowns)
def category_filter(request, search_term, forward_data) -> Q:
    parent_id = forward_data.get("parent_category")
    if parent_id:
        return Q(parent_id=parent_id)
    return Q()

# filter_query_lambda - How selection filters main list (filter widgets only)
def author_filter_query(request, selected_ids) -> Q:
    return Q(author_id__in=selected_ids)
```

### Example

Override `get_autocomplete_widget` on your `SBAdminRoleConfiguration` subclass:

```python
from django.db.models import Q

from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget
from django_smartbase_admin.engine.configuration import SBAdminRoleConfiguration

from blog.models import Author


def author_label(request, item):
    return f"{item.name} <{item.email}>"


def author_search(request, qs, model, search_term, language_code):
    if not search_term:
        return qs
    return qs.filter(Q(name__icontains=search_term) | Q(email__icontains=search_term))


class BlogRoleConfiguration(SBAdminRoleConfiguration):
    def get_autocomplete_widget(self, view, request, form_field, db_field, model, multiselect=False):
        if model == Author:
            return SBAdminAutocompleteWidget(
                form_field,
                model=model,
                multiselect=multiselect,
                label_lambda=author_label,
                search_query_lambda=author_search,
            )
        return super().get_autocomplete_widget(view, request, form_field, db_field, model, multiselect)
```

### Example: Dependent Dropdown with Forward

```python
# In a form, make "subcategory" dropdown depend on selected "category"
subcategory = forms.ModelChoiceField(
    queryset=Category.objects.all(),
    widget=SBAdminAutocompleteWidget(
        model=Category,
        multiselect=False,
        forward=["category"],  # Forward category field value
        filter_search_lambda=lambda req, term, fwd: Q(parent_id=fwd.get("category")) if fwd.get("category") else Q(),
    ),
)
```

### Example: Create on the fly with create_value_field + forward_to_create

Use this when you want “type to search” **and** the ability to create a missing value from the input. Creation is enabled only when:
- `allow_add=True`
- `create_value_field` is set
- widget is **not** multiselect (creation is currently not supported for multiselect)

```python
from django import forms
from django.db.models import Q

from django_smartbase_admin.admin.admin_base import SBAdminBaseFormInit
from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget

from blog.models import Category


class CreateCategoryInlineForm(SBAdminBaseFormInit, forms.Form):
    # NOTE: used by SBAdminAutocompleteWidget to detect FK fields and store them as `<field>_id` on create
    model = Category

    parent = forms.ModelChoiceField(
        label="Parent category",
        required=False,
        queryset=Category.objects.all(),
        widget=SBAdminAutocompleteWidget(
            model=Category,
            multiselect=False,
            label_lambda=lambda request, item: item.name,
        ),
    )

    category = forms.ModelChoiceField(
        label="Category",
        queryset=Category.objects.all(),
        widget=SBAdminAutocompleteWidget(
            model=Category,
            multiselect=False,
            allow_add=True,
            create_value_field="name",          # new Category(name="<typed>")
            forward=["parent"],                 # makes `parent` available in `forward_data`
            forward_to_create=["parent"],       # new Category(parent_id=<selected parent>)
            label_lambda=lambda request, item: item.name,
            filter_search_lambda=lambda req, term, fwd: Q(parent_id=fwd.get("parent")) if fwd.get("parent") else Q(),
        ),
    )
```

**Key points (creation):**
- `forward_to_create` pulls values from the widget’s `forward` data, so the field must also be present in `forward=[...]`.
- For FK fields, SBAdmin will try to store forwarded values under `<field>_id` during creation (so `Model.objects.create(**data)` accepts raw PKs). This requires the form to expose the model via `form.model` (see `model = Category` above).

**Key points:**
- `search_query_lambda` should search the same fields shown in `label_lambda` for intuitive UX
- `filter_search_lambda` runs BEFORE search - use for dependent dropdowns
- `search_query_lambda` defines WHICH fields to search
- Global config does NOT apply to manually-created widgets - pass lambdas directly

### Subclassing for Computed Label Values

When `label_lambda` needs a computed value (like a count from related tables), subclass `SBAdminAutocompleteWidget` and override `get_queryset` to add the annotation:

```python
from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget

from blog.models import Category, Article


class CategoryAutocompleteWidget(SBAdminAutocompleteWidget):
    """Autocomplete widget with article count annotation."""

    def get_queryset(self, request=None):
        qs = super().get_queryset(request)
        article_count_subquery = Subquery(
            Article.objects.filter(category=OuterRef("pk"))
            .values("category")
            .annotate(count=Count("id"))
            .values("count")
        )
        return qs.annotate(
            article_count=Coalesce(article_count_subquery, 0)
        )


# Usage in form
class ArticleForm(SBAdminBaseFormInit, forms.Form):
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        widget=CategoryAutocompleteWidget(
            model=Category,
            multiselect=False,
            label_lambda=lambda request, item: f"{item.name} ({item.article_count} articles)",
        ),
    )
```

**Why subclass instead of annotating the form field queryset?**
- The autocomplete widget fetches its own data via `get_queryset()` - it does NOT use the form field's queryset
- The form field queryset is only used for validation and `cleaned_data`
- Annotations in the widget's `get_queryset` are available to `label_lambda`

**Why use Subquery instead of Count?**
- Multiple `Count()` aggregates on related tables create Cartesian products
- Example: `Count("articles") + Count("children")` with 2 articles and 2 children returns 8 instead of 4
- Separate `Subquery` annotations avoid this by calculating each count independently

---

## Pre-filtered List Views (sbadmin_list_view_config)

Use `sbadmin_list_view_config` to define pre-filtered view tabs that appear at the top of the list view.

### Usage

```python
class ArticleAdmin(SBAdmin):
    sbadmin_list_view_config = [
        {
            "name": "Published",
            "url_params": {"filterData": {"status": "published"}},
        },
        {
            "name": "Drafts",
            "url_params": {"filterData": {"status": "draft"}},
        },
    ]
    
    list_filter = ("status",)
```

### Structure

| Key | Type | Description |
|-----|------|-------------|
| `name` | str | **Required**. Tab label shown in the UI |
| `url_params` | dict | **Required**. Contains `filterData` with filter key-value pairs |

### Filter Data Keys

The keys in `filterData` should match:
- Model field names for direct fields
- `filter_field` value from `SBAdminField` for custom filter fields

An "All" tab is automatically added as the first tab.

**Source:** `django_smartbase_admin/engine/admin_base_view.py` - `SBAdminBaseListView.sbadmin_list_view_config`

---

## Logo Customization

Override default logo by placing files in your static directory:
- `static/sb_admin/images/logo.svg` - Light mode
- `static/sb_admin/images/logo_light.svg` - Dark mode

---

## Contributing to This Document

When adding new information to this document, follow these guidelines:

### Use the Demo Schema

All examples must use models from the [Demo Schema Reference](#demo-schema-reference):
- `Article`, `Category`, `Tag`, `Author`, `Comment`, `ArticleTag`
- App name: `blog`
- Admin classes: `ArticleAdmin`, `CategoryAdmin`, etc.
- View IDs: `blog_article`, `blog_category`, etc.

If the demo schema doesn't cover your use case, extend it in the Demo Schema section first.

### Structure for New Sections

```markdown
## Section Title

Brief explanation of what this covers and when to use it.

### Subsection (if needed)

Code example:

```python
# Complete, runnable example using demo schema
```

**Key points:**
- Important gotcha or tip
- Another key point
```

### Checklist Before Adding

- [ ] Uses demo schema models (Article, Category, Tag, Author, Comment)
- [ ] Code examples are complete and runnable (not fragments)
- [ ] Added entry to Table of Contents with brief description
- [ ] No generic names like `MyModel`, `RelatedModel`, `SomeField`
- [ ] Includes "Key points" or gotchas if there are non-obvious behaviors
- [ ] Shows both ❌ BAD and ✅ GOOD patterns for common mistakes

### Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Admin class | `{Model}Admin` | `ArticleAdmin` |
| Form class | `{Action}Form` | `AssignCategoryForm` |
| View class | `{Action}View` | `AssignCategoryView` |
| Filter widget | `{Model}FilterWidget` | `TagFilterWidget` |
| Autocomplete widget | `{Model}AutocompleteWidget` | `CategoryAutocompleteWidget` |
| Lambda functions | `{model}_{purpose}` | `author_label`, `author_search` |
| Annotation keys | `{field}_val` or `{field}_arr` | `author_name_val`, `tag_names_arr` |

### What NOT to Add

- Implementation details that change frequently
- Workarounds for bugs (fix the bug instead)
- Features not yet released
- Duplicate information already covered elsewhere
