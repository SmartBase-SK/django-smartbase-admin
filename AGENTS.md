# Developer & AI Agent Reference

This document provides key patterns and gotchas for developers and AI assistants working with django-smartbase-admin.

---

## Table of Contents

| Section | What it covers |
|---------|----------------|
| [Demo Schema Reference](#demo-schema-reference) | Models used in all examples (Article, Category, Tag, Author, Comment) |
| [SBAdminField](#sbadminfield---list-display-columns) | Defining list columns, annotations, `supporting_annotates`, admin methods, ordering with computed fields, `sbadmin_list_display_data` |
| [Configuration](#configuration) | `INSTALLED_APPS`, role config, menu items, queryset restrictions, custom permissions |
| [Filter Widgets](#filter-widgets) | Built-in widgets, custom filters, `filter_query_lambda` for M2M filtering |
| [Admin Registration](#admin-registration) | `@admin.register` with `sb_admin_site`, `sbadmin_list_filter` vs `list_filter` |
| [Selection Actions](#selection-actions-bulk-actions) | Modal forms for bulk operations, `ListActionModalView`, confirmation modals, `SBAdminCustomAction` params, per-action permissions, success/error handling |
| [Field Formatters](#field-formatters) | Badge formatters, `array_badge_formatter`, `BadgeType` options |
| [View on Site link in list](#view-on-site-link-in-list) | List column with "View on site" icon via admin method, redirect view, `view_on_site_link_formatter` |
| [Performance Optimization](#performance-optimization) | `Subquery` patterns, `ArrayAgg`, avoiding N+1 queries |
| [Common Errors](#common-errors) | Frequent errors and solutions |
| [Inlines](#inlines) | `SBAdminTableInline`, `SBAdminStackedInline` for related models |
| [Validated Singleton Inline Creation on Add](#validated-singleton-inline-creation-on-add) | Why default-only singleton inlines can be skipped and how SBAdmin creates them during add |
| [Global Autocomplete Widget Customization](#global-autocomplete-widget-customization) | `label_lambda`, `search_query_lambda`, dependent dropdowns, subclassing for computed values |
| [Pre-filtered List Views](#pre-filtered-list-views-sbadmin_list_view_config) | Tab-based filtered views with `sbadmin_list_view_config`, default tab from menu, programmatic URL building |
| [Detail View Layout (Sidebar)](#detail-view-layout-sidebar) | Placing fieldsets in the right sidebar using `DETAIL_STRUCTURE_RIGHT_CLASS` |
| [Detail View Tabs](#detail-view-tabs-sbadmin_tabs) | Organizing fieldsets and inlines into tabs with `sbadmin_tabs` |
| [Logo Customization](#logo-customization) | Override logo via static files |
| [URL-Callable Action Methods (`@sbadmin_action`)](#url-callable-action-methods-sbadmin_action) | `@sbadmin_action` decorator for URL-callable view methods |
| [SBAdmin Attribute Reference](#sbadmin-attribute-reference) | Quick reference for all `sbadmin_` prefixed attributes |
| [Audit Logging](#audit-logging) | Built-in audit trail — installation, configuration, skip models/fields, history button, programmatic entries, programmatic URLs |
| [Testing](#testing) | How to install test dependencies, run tests, and add new tests |
| [SBAdminWizardView](#sbadminwizardview) | Multi-step wizard with ``SBAdminWizardStep`` — attributes, lifecycle, formsets, navigation, template |
| [Contributing to This Document](#contributing-to-this-document) | Guidelines for adding new sections and examples |

**Quick lookup:**
- **Adding a column?** → [SBAdminField](#sbadminfield---list-display-columns)
- **Extra data for formatters?** → [sbadmin_list_display_data](#sbadmin_list_display_data---extra-data-fields)
- **Filtering by related model?** → [Filter Widgets](#filter-widgets) (filter_query_lambda)
- **Bulk action with modal?** → [Selection Actions](#selection-actions-bulk-actions)
- **Confirmation dialog (no form)?** → [Confirmation-Only Modals](#confirmation-only-modals-no-form-fields)
- **Per-action permissions?** → [Per-Action Permissions](#per-action-permissions-has_permission_for_action)
- **Manual audit log entries?** → [Programmatic Audit Entries](#programmatic-audit-entries-_create_audit_log)
- **N+1 query issues?** → [Performance Optimization](#performance-optimization)
- **Autocomplete customization?** → [Global Autocomplete Widget Customization](#global-autocomplete-widget-customization)
- **Ordering by computed field?** → [Ordering with Computed SBAdminField](#ordering-with-computed-sbadminfield)
- **Menu opens filtered tab?** → [Default Tab and Menu Link to Filtered View](#default-tab-and-menu-link-to-filtered-view)
- **Building pre-filtered URLs?** → [Building Pre-filtered URLs Programmatically](#building-pre-filtered-urls-programmatically)
- **Fields in sidebar?** → [Detail View Layout (Sidebar)](#detail-view-layout-sidebar)
- **Fieldsets/inlines in tabs?** → [Detail View Tabs](#detail-view-tabs-sbadmin_tabs)
- **Custom permission system (non-Django)?** → [Custom Permission System](#custom-permission-system-has_permission)
- **Audit trail / change history?** → [Audit Logging](#audit-logging)
- **“View on site” icon next to a list column?** → [View on Site link in list](#view-on-site-link-in-list)
- **Required singleton inline not created on add?** → [Validated Singleton Inline Creation on Add](#validated-singleton-inline-creation-on-add)
- **Making a method URL-callable?** → [URL-Callable Action Methods (`@sbadmin_action`)](#url-callable-action-methods-sbadmin_action)

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

class ArticleMeta(models.Model):
    """Singleton metadata row for each Article."""
    article = models.OneToOneField(Article, on_delete=models.CASCADE, related_name="meta")
    heading = models.CharField(max_length=200, default="Metadata")
    description = models.TextField(blank=True, default="")
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

### Ordering with Computed SBAdminField

**Problem:** You have a computed field in `sbadmin_list_display` (with `annotate=`) and want to use it in the `ordering` attribute:

```python
from django.db.models import Case, TextField, Value, When

from blog.models import Article

# ❌ BAD - causes FieldError on detail/change page
@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    sbadmin_list_display = (
        SBAdminField(
            name="status_display",
            title="Status",
            annotate=Case(
                When(status="published", then=Value("Published")),
                When(status="draft", then=Value("Draft")),
                default=Value("Other"),
                output_field=TextField(),
            ),
        ),
    )
    ordering = ("status_display", "-created_at")  # Fails on detail page!
```

**Why it fails:** Django's `ordering` attribute is applied via `get_queryset()` which is called for BOTH list and detail views. The computed annotation only exists in the list view context (via `sbadmin_list_display`). When loading the detail/change page, Django tries to resolve `status_display` as a database field but it doesn't exist.

**Solution:** Override `get_list_ordering()` which is only used for the list view:

```python
from django.db.models import Case, TextField, Value, When

from blog.models import Article

# ✅ GOOD - get_list_ordering is only called for list view
@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    sbadmin_list_display = (
        SBAdminField(
            name="status_display",
            title="Status",
            annotate=Case(
                When(status="published", then=Value("Published")),
                When(status="draft", then=Value("Draft")),
                default=Value("Other"),
                output_field=TextField(),
            ),
        ),
    )
    # No class-level `ordering` attribute!

    def get_list_ordering(self, request):
        """Define ordering for list view - can use computed fields."""
        return ("status_display", "-created_at")
```

**Key points:**
- SBAdmin uses `get_list_ordering()` for list view ordering (not Django's `get_ordering()`)
- `get_list_ordering()` is only called for the list view, so computed fields from `sbadmin_list_display` are available
- No need to check for detail/change pages - this method is list-view specific
- For simple ordering without computed fields, you can still use the `ordering` class attribute

### sbadmin_list_display_data - Extra Data Fields

Use `sbadmin_list_display_data` to ensure data is **always fetched**, even when the user hides a column that provides it.

**Problem**: Column A provides data via `supporting_annotates`. Column B needs that data. User hides Column A → data is no longer fetched → Column B breaks.

**Solution**: List the data in `sbadmin_list_display_data` to ensure it's always available.

```python
class ArticleAdmin(SBAdmin):
    sbadmin_list_display = (
        SBAdminField(
            name="author_display",  # User CAN hide this column
            title="Author",
            annotate=F("author__name"),
            supporting_annotates={
                "author_id_val": F("author_id"),
            },
        ),
        SBAdminField(
            name="author_link",  # This column needs author_id_val
            title="Profile",
            annotate=Value("", output_field=TextField()),
        ),
    )

    # Ensure author_id_val is ALWAYS fetched, even if "Author" column is hidden
    sbadmin_list_display_data = ("author_id_val",)

    def author_link(self, obj_id, value, **additional_data):
        author_id = additional_data.get("author_id_val")
        return format_html('<a href="/authors/{}">View</a>', author_id)
```

**Key points:**
- Use when **another column depends on data** from a column that can be hidden
- Use for **model fields** needed in formatters (e.g., `author_id` for links)
- Use for **hidden data-only fields** defined with `list_visible=False`
- `supporting_annotates` are only fetched when their parent column is visible - use this to force fetch

For data-only fields (hidden columns with annotations), define the field and reference it:

```python
class ArticleAdmin(SBAdmin):
    sbadmin_list_display = (
        SBAdminField(
            name="computed_score",
            annotate=F("views") + F("comments_count"),
            list_visible=False,  # Hidden column
        ),
        # ... other visible columns
    )

    # Reference the hidden field to include it in the queryset
    sbadmin_list_display_data = ("computed_score",)
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

### Custom Permission System (`has_permission`)

By default, `SBAdminRoleConfiguration.has_permission()` uses Django's built-in model permissions (`user.has_perm("app.view_model")`, etc.). If your project uses a different permission system (e.g., external IAM, JWT claims, session-based permissions), you can override `has_permission()` on your role configuration subclass to replace this behavior globally.

**How the permission chain works:**

Every permission check in SBAdmin flows through the role configuration:

```
SBAdminBaseView.has_permission()
    → SBAdminViewService.has_permission()
        → SBAdminRoleConfiguration.has_permission()   ← override this
```

This covers **all** SBAdmin-routed views: admin list/detail views, inlines, autocomplete widgets, and custom actions. By overriding `has_permission()` on the configuration, you get a single entry point for your custom permission logic. Since SBAdmin uses a fully custom menu (via `SBAdminMenuItem`), Django's admin index page is not used, so `has_module_permission()` does not need to be overridden.

**Example — session-based permissions:**

```python
# myapp/sbadmin_config.py
from django_smartbase_admin.engine.configuration import SBAdminConfigurationBase, SBAdminRoleConfiguration
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView

PERM_ADMIN = "admin"
PERM_ACCESS = "access"

# Map model names to required permissions (beyond PERM_ACCESS)
MODEL_PERMISSIONS = {
    "article": [],                  # Only PERM_ACCESS needed
    "comment": ["moderator"],       # Needs PERM_ACCESS + moderator
}
DEFAULT_PERMISSIONS = ["editor"]    # Fallback for unlisted models


def _get_session_permissions(request) -> set[str]:
    """Get permissions from session (populated at login by your auth backend)."""
    return set(request.session.get("permissions", []))


def has_model_permission(request, model_name: str) -> bool:
    """Check if user has permission to access a specific model."""
    permissions = _get_session_permissions(request)

    if PERM_ADMIN in permissions:
        return True  # Admin bypasses all checks

    if PERM_ACCESS not in permissions:
        return False  # No base access

    additional = MODEL_PERMISSIONS.get(model_name.lower(), DEFAULT_PERMISSIONS)
    if not additional:
        return True  # Only PERM_ACCESS required
    return any(perm in permissions for perm in additional)


class AppRoleConfiguration(SBAdminRoleConfiguration):
    """Role configuration with custom permission system."""

    def has_permission(
        self, request, request_data, view, model=None, obj=None, permission=None
    ):
        """Replace Django model permissions with custom session-based permissions.

        This is called for all permission checks routed through SBAdmin:
        admin views, inlines, autocomplete widgets, and custom actions.
        """
        if not request.user.is_authenticated:
            return False
        if model:
            return has_model_permission(request, model._meta.model_name)
        return True


_role_config = AppRoleConfiguration(
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
- Override `has_permission()` on your `SBAdminRoleConfiguration` subclass — this is the **single central hook** for all permission checks (views, inlines, autocomplete widgets, actions)
- The method signature is: `has_permission(self, request, request_data, view, model=None, obj=None, permission=None)`
- SBAdmin uses a custom menu (`SBAdminMenuItem`), so Django's `has_module_permission()` is irrelevant — you do **not** need to override it
- Inlines (`SBAdminTableInline`, `SBAdminStackedInline`) don't need permission overrides — their checks go through the configuration's `has_permission()`
- The default implementation checks `request.user.has_perm()` — your override completely replaces this, so Django model permissions are not consulted at all

### `SBAdminRoleConfiguration` — Overridable Methods Summary

`SBAdminRoleConfiguration` is the central place to customize SBAdmin behavior. All overrides go on a single subclass:

| Method | Purpose | Documented in |
|--------|---------|---------------|
| `has_permission()` | Replace Django model permissions with custom system | [Custom Permission System](#custom-permission-system-has_permission) |
| `restrict_queryset()` | Apply global queryset filters (e.g., hide soft-deleted records) | [Global Queryset Filtering](#global-queryset-filtering) |
| `get_autocomplete_widget()` | Customize autocomplete labels, search, and dependent dropdowns | [Global Autocomplete Widget Customization](#global-autocomplete-widget-customization) |

**Typical subclass combining all three:**

```python
# myapp/sbadmin_config.py
from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget
from django_smartbase_admin.engine.configuration import SBAdminConfigurationBase, SBAdminRoleConfiguration
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView

from myapp.models import Author
from myapp.permissions import has_model_permission
from myapp.queryset_restrictions import apply_model_restrictions, author_label, author_search


class AppRoleConfiguration(SBAdminRoleConfiguration):
    """Role configuration with custom permissions, queryset restrictions, and autocomplete widgets."""

    def has_permission(self, request, request_data, view, model=None, obj=None, permission=None):
        if not request.user.is_authenticated:
            return False
        if model:
            return has_model_permission(request, model._meta.model_name)
        return True

    def restrict_queryset(self, qs, model, request, request_data, global_filter=True, global_filter_data_map=None):
        return apply_model_restrictions(qs, request=request)

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


_role_config = AppRoleConfiguration(
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

---

## View on Site link in list

You can show a “View on site” icon next to a list column value (e.g. article title) that opens the object’s frontend URL in a new tab. The link goes through a **redirect view**: no per-row database or URL lookup is done when rendering the list; the redirect runs only when the user clicks the icon.

### Enabling the link

Use an **admin method** (a column whose name matches a method on the admin). The method calls `view_on_site_link_formatter` and passes `sbadmin_view_id` and `sbadmin_view_on_site`; the formatter cannot be used as `python_formatter` because the list action does not inject these kwargs into `additional_data`.

```python
from django.contrib import admin
from django.db.models import F
from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.field_formatter import view_on_site_link_formatter

from blog.models import Article


@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    def get_title_with_view_on_site(self, object_id, value, **kwargs):
        """Column: title + View on site icon. Pass view id and flag for the formatter."""
        return view_on_site_link_formatter(
            object_id,
            value,
            sbadmin_view_id=self.get_id(),
            sbadmin_view_on_site=True,
        )

    sbadmin_list_display = (
        SBAdminField(
            name="get_title_with_view_on_site",
            title="Title",
            annotate=F("title"),
        ),
        # ... other columns
    )
```

**Redirect view and URL**  
The framework provides `ViewOnSiteRedirectView`:

- Path: `view-on-site/<str:view>/<int:object_id>/`
- URL name: `sb_admin:view_on_site_redirect`  

The view resolves the admin from the `view` id, loads the object, calls `get_view_on_site_url(obj)`, and redirects. If the URL is `None`, it returns 404.

**Formatter kwargs**  
`view_on_site_link_formatter(object_id, value, **kwargs)` expects:

- `sbadmin_view_id`: the list view id (e.g. `blog_article`), used to build the redirect URL.
- `sbadmin_view_on_site`: optional, default `True`; if falsy, the formatter returns only the value (no icon/link).

Because these are not passed to `python_formatter`’s `additional_data`, you must use an admin method that calls the formatter with these kwargs explicitly.

### CSS classes

The formatter outputs:

- **Wrapper:** `view-on-site-cell` — flex container for the value + link.
- **Link:** `view-on-site-link` — the “View on site” anchor (icon, tooltip, opens in new tab).

Styles live in `static/sb_admin/src/css/_tabulator.css`: the icon is hidden on small screens and fades in on row hover (or when the link has focus).

### Summary

| Piece | Location / name |
|-------|------------------|
| Redirect view | `ViewOnSiteRedirectView` in `views/view_on_site_redirect_view.py` |
| URL name | `sb_admin:view_on_site_redirect` (kwargs: `view`, `object_id`) |
| Formatter | `view_on_site_link_formatter` in `engine/field_formatter.py` |
| URL for redirect | `get_view_on_site_url(self, obj)` — already on every admin. |
| CSS | `.view-on-site-cell`, `.view-on-site-link` in `_tabulator.css` |

**Key points:**
- The list only renders a link to the redirect URL; the redirect runs once on click and then calls `get_view_on_site_url(obj)`.
- Use an admin method (not `python_formatter`) so you can pass `sbadmin_view_id` and `sbadmin_view_on_site` to the formatter.

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
| `ChoiceFilterWidget` | Static choices (single selection) |
| `MultipleChoiceFilterWidget` | Static choices (multiple selection) |

> **Recommendation:** Prefer `MultipleChoiceFilterWidget` over `ChoiceFilterWidget` for choice-based filters. It provides a better UX and gives users more flexibility to select multiple values at once.

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
    sbadmin_list_filter = (...)  # Preferred for SBAdminField names
    search_fields = (...)
```

### Default Visible Filters: sbadmin_list_filter vs list_filter

Use `sbadmin_list_filter` to specify which filters are visible by default. This attribute accepts `SBAdminField` `name` values directly, making it the preferred choice when using computed/annotated fields.

**When to use each:**

| Attribute | Use When | Accepts |
|-----------|----------|---------|
| `sbadmin_list_filter` | You have `SBAdminField` with `annotate=` or custom `filter_widget` | SBAdminField `name` values |
| `list_filter` | All filters are simple model fields | Model field names or `filter_field` values |

```python
# ❌ BAD - Django's list_filter fails validation on annotated fields
sbadmin_list_display = (
    SBAdminField(
        name="status_display",  # Computed annotation, NOT a model field
        annotate=Case(...),
        filter_widget=MultipleChoiceFilterWidget(...),
    ),
    SBAdminField(
        name="tags_display",  # Computed annotation
        annotate=get_tag_names_subquery(),
        filter_widget=AutocompleteFilterWidget(...),
    ),
)

list_filter = (
    "status_display",  # ❌ Fails: admin.E116 - not a model field
    "tags_display",    # ❌ Fails: admin.E116 - not a model field
)
```

```python
# ✅ GOOD - sbadmin_list_filter accepts SBAdminField names
sbadmin_list_display = (
    SBAdminField(
        name="status_display",
        annotate=Case(...),
        filter_widget=MultipleChoiceFilterWidget(...),
    ),
    SBAdminField(
        name="tags_display",
        annotate=get_tag_names_subquery(),
        filter_widget=AutocompleteFilterWidget(...),
    ),
)

sbadmin_list_filter = (
    "status_display",  # ✅ Works: matches SBAdminField name
    "tags_display",    # ✅ Works: matches SBAdminField name
)
```

**For simple model fields**, both work:

```python
sbadmin_list_display = (
    "title",
    SBAdminField(name="status", filter_field="status"),
    SBAdminField(name="author_name", filter_field="author__email"),
    SBAdminField(name="comment_count", filter_disabled=True),
)

# Either works for model fields:
sbadmin_list_filter = ("title", "status", "author_name")
# OR
list_filter = ("title", "status", "author__email")

---

## Selection Actions (Bulk Actions)

Add custom actions that operate on selected rows in the list view.

```python
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils.translation import gettext_lazy as _
from django_htmx.http import trigger_client_event
from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminBaseFormInit
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget
from django_smartbase_admin.engine.actions import SBAdminFormViewAction
from django_smartbase_admin.engine.const import TABLE_RELOAD_DATA_EVENT_NAME
from django_smartbase_admin.engine.modal_view import ListActionModalView

from blog.models import Article, Category
```

### Modal with Form

For actions that need user input, use `SBAdminFormViewAction` with `ListActionModalView`:

```python
class AssignCategoryForm(SBAdminBaseFormInit, forms.Form):
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
        category = form.cleaned_data["category"]
        selection_queryset.update(category=category)


@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    def get_sbadmin_list_selection_actions(self, request):
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

### Confirmation-Only Modals (No Form Fields)

Use an empty form for confirm/cancel dialogs. The modal renders the title with Close/Continue buttons.

```python
class ConfirmForm(SBAdminBaseFormInit, forms.Form):
    pass


class ArchiveArticlesView(ListActionModalView):
    form_class = ConfirmForm
    modal_title = _("Archive Selected Articles")

    def process_form_valid(self, request, form):
        selection_queryset = self.get_selection_queryset(request, form)
        count = selection_queryset.update(status="archived")

        messages.success(request, _("%d article(s) archived.") % count)
        notifications_html = render_to_string(
            "sb_admin/includes/notifications.html",
            {"messages": messages.get_messages(request)},
            request=request,
        )
        response = HttpResponse(notifications_html)
        trigger_client_event(response, "hideModal", {})
        trigger_client_event(response, TABLE_RELOAD_DATA_EVENT_NAME, {})
        return response


@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    def get_sbadmin_list_selection_actions(self, request):
        return [
            SBAdminFormViewAction(
                target_view=ArchiveArticlesView,
                title=_("Archive Selected"),
                view=self,
                action_id="archive_articles",
                open_in_modal=True,
                css_class="btn-destructive",
            ),
        ]
```

### SBAdminCustomAction Parameters

`SBAdminFormViewAction` extends `SBAdminCustomAction`. Available parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `title` | str | **Required** | Button label |
| `target_view` | class | **Required** (FormViewAction only) | The `ListActionModalView` subclass |
| `view` | SBAdmin | **Required** | The admin class instance (`self`) |
| `action_id` | str | `None` | Unique identifier for this action |
| `open_in_modal` | bool | `False` | Open the action in a modal dialog |
| `css_class` | str | `None` | CSS class for the button (e.g., `"btn-destructive"` for red) |
| `icon` | str | `None` | Icon name (from sprite set) |
| `group` | str | `None` | Group actions under a dropdown menu |
| `sub_actions` | list | `None` | Nested actions under this action |
| `no_params` | bool | `False` | If `True`, don't pass current list params to the action URL |
| `open_in_new_tab` | bool | `False` | Open action URL in a new browser tab |
| `url` | str | `None` | Direct URL (for non-form actions) |
| `template` | str | `None` | Custom template for the action button |

### Per-Action Permissions (`has_permission_for_action`)

Override `has_permission_for_action` on your admin class to control which actions are visible per request.

```python
PUBLISH_ACTION_ID = "publish_articles"


class ConfirmForm(SBAdminBaseFormInit, forms.Form):
    pass


class PublishArticlesView(ListActionModalView):
    form_class = ConfirmForm
    modal_title = _("Publish Selected Articles")

    def process_form_valid_list_selection_queryset(self, request, form, selection_queryset):
        selection_queryset.update(status="published")


class ArchiveArticlesView(ListActionModalView):
    form_class = ConfirmForm
    modal_title = _("Archive Selected Articles")

    def process_form_valid_list_selection_queryset(self, request, form, selection_queryset):
        selection_queryset.update(status="archived")


# ❌ BAD - Conditionally building the action list based on request.
# URL handlers are registered via setattr on the singleton during the first request.
# If a non-editor visits first, PublishView handler is never registered.
@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    def get_sbadmin_list_selection_actions(self, request):
        actions = []
        permissions = set(request.session.get("permissions", []))
        if "editor" in permissions:
            actions.append(
                SBAdminFormViewAction(
                    target_view=PublishArticlesView,
                    title=_("Publish Selected"),
                    view=self,
                    action_id=PUBLISH_ACTION_ID,
                    open_in_modal=True,
                ),
            )
        actions.append(
            SBAdminFormViewAction(
                target_view=ArchiveArticlesView,
                title=_("Archive Selected"),
                view=self,
                action_id="archive_articles",
                open_in_modal=True,
            ),
        )
        return actions


# ✅ GOOD - Always return all actions, use has_permission_for_action to filter visibility
@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    def get_sbadmin_list_selection_actions(self, request):
        return [
            SBAdminFormViewAction(
                target_view=PublishArticlesView,
                title=_("Publish Selected"),
                view=self,
                action_id=PUBLISH_ACTION_ID,
                open_in_modal=True,
            ),
            SBAdminFormViewAction(
                target_view=ArchiveArticlesView,
                title=_("Archive Selected"),
                view=self,
                action_id="archive_articles",
                open_in_modal=True,
                css_class="btn-destructive",
            ),
        ]

    def has_permission_for_action(self, request, action):
        if getattr(action, "action_id", None) == PUBLISH_ACTION_ID:
            permissions = set(request.session.get("permissions", []))
            if "editor" not in permissions and "admin" not in permissions:
                return False
        return super().has_permission_for_action(request, action)
```

**Key points:**
- Always return **all** actions from `get_sbadmin_list_selection_actions` — use `has_permission_for_action` to filter visibility
- Do NOT conditionally build the action list based on request — URL handlers are registered on the singleton during the first request and cached via `init_actions`
- The default `has_permission_for_action` delegates to `SBAdminRoleConfiguration.has_permission()`
- `SBAdminFormViewAction` modal views are automatically URL-callable — no extra decoration needed
- When using `SBAdminCustomAction` with `action_id` pointing to a method, that method must be decorated with [`@sbadmin_action`](#url-callable-action-methods-sbadmin_action)

### Modal Error Handling

```python
class AssignCategoryView(ListActionModalView):
    def process_form_valid(self, request, form):
        try:
            return super().process_form_valid(request, form)
        except ValidationError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)
```

The modal template automatically displays `form.errors` and `form.non_field_errors` in a styled alert box.

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
| "Cannot resolve keyword 'X' into field" on detail page | Using computed `SBAdminField` name in `ordering` | Override `get_list_ordering()` - see [Ordering with Computed SBAdminField](#ordering-with-computed-sbadminfield) |
| "admin.E116: The value of 'list_filter[N]' refers to 'X', which does not refer to a Field" | Using `list_filter` with `SBAdminField` names for annotated fields | Use `sbadmin_list_filter` instead - see [Default Visible Filters](#default-visible-filters-sbadmin_list_filter-vs-list_filter) |

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

## Validated Singleton Inline Creation on Add

Django treats extra inline forms with default-only values as unchanged. For required singleton inlines, this may result in skipped creation unless the form is considered changed during validation.

### Behavior in SBAdmin

For parent **add** flow, SBAdmin supports validated singleton creation with:

- `min_num = 1`
- `max_num = 1`
- `validate_min = True`
- `validate_max = True`

When these conditions are met, SBAdmin marks the first extra inline form as changed during formset `full_clean()`. This lets normal validation/save flow create the related object (including default-only values).

### ❌ BAD - Singleton inline can still be skipped

```python
from django.contrib import admin
from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminStackedInline
from django_smartbase_admin.admin.site import sb_admin_site

from blog.models import Article, ArticleMeta


class ArticleMetaInline(SBAdminStackedInline):
    model = ArticleMeta
    min_num = 1
    max_num = 1
    # Missing validate_min / validate_max
    can_delete = False
    extra = 1


@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    inlines = [ArticleMetaInline]
```

### ✅ GOOD - Validated singleton is created on add

```python
from django.contrib import admin
from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminStackedInline
from django_smartbase_admin.admin.site import sb_admin_site

from blog.models import Article, ArticleMeta


class ArticleMetaInline(SBAdminStackedInline):
    model = ArticleMeta
    min_num = 1
    max_num = 1
    validate_min = True
    validate_max = True
    can_delete = False
    extra = 1


@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    inlines = [ArticleMetaInline]
```

**Key points:**
- Scope is intentionally add-only to keep update flow conservative.
- Validation still runs normally; this does not bypass field/model validation.
- If required inline fields have no defaults and remain empty, validation can still fail (expected).

---

## Global Autocomplete Widget Customization

Override `get_autocomplete_widget` on your `SBAdminRoleConfiguration` subclass to customize autocomplete widgets globally. This applies to all auto-generated admin form fields including inlines.

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | Model class | **Required**. The Django model to query |
| `multiselect` | bool | Allow multiple selections (default: `True`) |
| `label_lambda` | callable | `(request, item) -> str` - Format how items appear in dropdown |
| `value_lambda` | callable | `(request, item) -> any` - Extract value from item (default: primary key) |
| `value_field` | str | Field name to use as value (alternative to `value_lambda`) |
| `search_query_lambda` | callable | `(request, qs, model, search_term, lang_code) -> QuerySet` - Define which fields to search. Default searches all CharField/TextField |
| `filter_search_lambda` | callable | `(request, search_term, forward_data) -> Q` - Pre-filter queryset before search. Use for dependent dropdowns (with `forward`) or general filtering (e.g., limit to items with related data) |
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

# filter_search_lambda - Pre-filter queryset before search
# Use case 1: Dependent dropdowns (filter based on another field's value)
def subcategory_filter(request, search_term, forward_data) -> Q:
    parent_id = forward_data.get("parent_category")
    if parent_id:
        return Q(parent_id=parent_id)
    return Q()

# Use case 2: General filtering (limit to items with related data)
def content_type_filter(request, search_term, forward_data) -> Q:
    # Only show content types that have audit logs
    ct_ids = AuditLog.objects.values_list("content_type", flat=True).distinct()
    return Q(pk__in=ct_ids)

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
- `filter_search_lambda` runs BEFORE search - use for dependent dropdowns OR general pre-filtering (e.g., limit to items with related data)
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

### Autocomplete for Text Field Values (Not ForeignKey)

When you need an autocomplete that stores a text value (not a ForeignKey), use `SBAdminAutocompleteWidget` with `label_lambda` and `value_lambda` to return text instead of the model's pk.

#### Simple Inline Approach (No Distinct)

When duplicates in the dropdown are acceptable (or the source field is already unique), use lambdas directly:

```python
from django import forms
from django.contrib import admin
from django.db.models import Q

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminBaseForm
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget

from blog.models import Article, Author


class ArticleForm(SBAdminBaseForm):
    """Form with author name autocomplete storing text value."""

    author_name = forms.CharField(
        label="Author Name",
        required=False,
        widget=SBAdminAutocompleteWidget(
            model=Author,
            multiselect=False,
            label_lambda=lambda req, item: item.name,
            value_lambda=lambda req, item: item.name,
            filter_search_lambda=lambda req, search, fwd: Q(is_active=True),
        ),
    )

    class Meta:
        model = Article
        fields = "__all__"


@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    model = Article
    form = ArticleForm
```

#### Subclass Approach (With Distinct or Custom Lookup)

Use this when there's no direct model relationship - you're storing a text value (not a FK) but want autocomplete suggestions from another model's field. The subclass tells the widget how to look up and display values from a field that isn't the primary key:

```python
from django import forms
from django.contrib import admin

from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminBaseForm
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget

from blog.models import Article, Author


class AuthorEmailAutocompleteWidget(SBAdminAutocompleteWidget):
    """Autocomplete widget for distinct author emails."""

    def get_queryset(self, request=None):
        return (
            Author.objects.exclude(email__exact="")
            .exclude(email__isnull=True)
            .order_by("email")
            .distinct("email")
        )

    def get_value_field(self):
        return "email"  # Field to look up existing values (not pk)

    def get_label(self, request, item):
        return item.email

    def get_value(self, request, item):
        return item.email


class ArticleForm(SBAdminBaseForm):
    """Form with author email autocomplete from distinct Author emails."""

    author_email = forms.CharField(
        label="Author Email",
        required=False,
        widget=AuthorEmailAutocompleteWidget(model=Author, multiselect=False),
    )

    class Meta:
        model = Article
        fields = "__all__"


@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    model = Article
    form = ArticleForm
```

**When to use each approach:**

| Approach | Use When |
|----------|----------|
| Inline lambdas | Source field values are unique, duplicates are acceptable, editing existing values not needed |
| Subclass | No FK relationship, need `.distinct()`, or need to look up existing values when editing (requires `get_value_field()`) |

**Key points:**
- Form field is `CharField` (not `ModelChoiceField`) since we're storing a text value
- Form must inherit from `SBAdminBaseForm` for proper widget initialization
- `label_lambda` and `value_lambda` return text field value instead of model's pk
- **Critical:** Override `get_value_field()` to return the text field name - this is used to look up existing values when editing (default is `"id"` which fails for text values)
- Use `multiselect=False` for single selection
- `filter_search_lambda` returns a `Q` object - for `.distinct()` or complex queryset changes, subclass the widget and override `get_queryset()`

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

### Filter Data for Named Tabs

The keys in `filterData` should match:
- Model field names for direct fields
- `filter_field` value from `SBAdminField` for custom filter fields

**Value format in `filterData` depends on the filter widget type used by the field:**

| Filter Widget | Value Format in `filterData` | Example |
|---------------|------------------------------|---------|
| `ChoiceFilterWidget` | String | `"published"` |
| `MultipleChoiceFilterWidget` | **Array** of objects with `value` and `label` | `[{"value": "published", "label": "Published"}]` |

**Example: Pre-filtered tabs with MultipleChoiceFilterWidget:**

```python
class ArticleAdmin(SBAdmin):
    sbadmin_list_display = (
        SBAdminField(
            name="status",
            filter_widget=MultipleChoiceFilterWidget(choices=[
                ("published", "Published"),
                ("draft", "Draft"),
                ("archived", "Archived"),
            ]),
        ),
    )
    
    sbadmin_list_view_config = [
        {
            "name": "Published",  # Must be array even for single value
            "url_params": {"filterData": {"status": [{"value": "published", "label": "Published"}]}},
        },
        {
            "name": "Active",  # Multiple values in array
            "url_params": {"filterData": {"status": [
                {"value": "published", "label": "Published"},
                {"value": "draft", "label": "Draft"},
            ]}},
        },
    ]
    
    list_filter = ("status",)
```

> **Note:** `MultipleChoiceFilterWidget` values must always be an array (even for single selections) because the JavaScript uses `.map()` to parse the values.

### Displaying All Filters in Named Tabs

When switching to a named tab, only filters specified in `filterData` are shown in the filter bar above the table. To display all filter widgets (even those without values), include them with empty string (`""`):

```python
class ArticleAdmin(SBAdmin):
    sbadmin_list_display = (
        SBAdminField(name="status", filter_widget=MultipleChoiceFilterWidget(choices=[...])),
        SBAdminField(name="category", filter_widget=FromValuesAutocompleteWidget()),
        SBAdminField(name="author", filter_widget=AutocompleteFilterWidget(model=Author)),
    )
    
    sbadmin_list_view_config = [
        {
            "name": "Published",
            "url_params": {"filterData": {
                "status": [{"value": "published", "label": "Published"}],
                "category": "",  # Display filter widget (empty)
                "author": "",    # Display filter widget (empty)
            }},
        },
    ]
    
    list_filter = ("status", "category", "author")
```

> **Note:** The automatic "All" tab already displays all `list_filter` fields. For custom tabs, you must explicitly include each filter you want visible in the filter bar.

An "All" tab is automatically added as the first tab.

**Source:** `django_smartbase_admin/engine/admin_base_view.py` - `SBAdminBaseListView.sbadmin_list_view_config`

### Default Tab and Menu Link to Filtered View

By default, clicking a menu item opens the "All" tab. To make a custom tab the default (e.g., show "Published" articles when clicking the menu item):

1. Override `get_base_config` to reorder tabs so your custom tab is first
2. Override `get_menu_view_url` to construct a URL with filter parameters

```python
from django.contrib import admin
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.field import SBAdminField
from django_smartbase_admin.engine.filter_widgets import MultipleChoiceFilterWidget
from django_smartbase_admin.services.views import SBAdminViewService

from blog.models import Article


@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    model = Article

    sbadmin_list_display = (
        SBAdminField(
            name="status",
            filter_widget=MultipleChoiceFilterWidget(choices=[
                ("published", "Published"),
                ("draft", "Draft"),
                ("archived", "Archived"),
            ]),
        ),
        "title",
        "category",
    )

    sbadmin_list_filter = ("status",)

    sbadmin_list_view_config = [
        {
            "name": "Published",
            "url_params": {
                "filterData": {
                    "status": [{"value": "published", "label": "Published"}],
                }
            },
        },
    ]

    def get_base_config(self, request):
        """Reorder tabs: move custom tabs before 'All'.

        Default order from super(): [All, Published, ...]
        After rotation: [Published, ..., All]
        """
        configs = super().get_base_config(request)
        return configs[1:] + configs[:1]

    def get_menu_view_url(self, request) -> str:
        """Build menu URL that opens the first custom tab (Published) directly."""
        base = reverse(f"sb_admin:{self.get_id()}_changelist")
        filter_data = self.sbadmin_list_view_config[0]["url_params"]["filterData"]
        params = SBAdminViewService.build_list_params_url(self.get_id(), filter_data)
        return f"{base}?{params}"
```

**How it works:**
- `get_base_config` returns the list of tab configs. The default order is `[All, ...custom tabs...]`. Rotating with `configs[1:] + configs[:1]` puts custom tabs first and "All" last.
- `get_menu_view_url` is called by the menu rendering to get the URL for this model's menu item. By default it returns the changelist URL (which opens "All"). Overriding it to include filter params makes the menu link open the filtered view directly.
- The tab order and menu URL are independent — override both for a consistent experience.

**Key points:**
- `get_base_config` rotation (`configs[1:] + configs[:1]`) works for any number of custom tabs — the first custom tab becomes the default
- `self.get_id()` returns the view ID in `{app_label}_{model_name}` format
- `SBAdminViewService.build_list_params_url` encodes filter data into URL query parameters
- Without `get_menu_view_url` override, clicking the menu item would show the "All" tab even if `get_base_config` reorders tabs (the menu URL is constructed separately)

### Building Pre-filtered URLs Programmatically

Use `SBAdminViewService.build_list_params_url()` to generate URLs with pre-applied filters from Python code (e.g., for redirects or links between admin pages).

```python
from django.urls import reverse
from django_smartbase_admin.services.views import SBAdminViewService

# View ID follows pattern: {app_label}_{model_name}
VIEW_ID = "blog_article"

# Filter data format depends on the filter widget type
filter_data = {
    # AutocompleteFilterWidget: array of {value, label}
    "category": [
        {"value": 5, "label": "Technology"},
    ],
    # MultipleChoiceFilterWidget: array of {value, label}
    "status": [
        {"value": "published", "label": "Published"},
        {"value": "draft", "label": "Draft"},
    ],
}

# Build the URL
base_url = reverse("sb_admin:blog_article_changelist")
params_str = SBAdminViewService.build_list_params_url(VIEW_ID, filter_data)
full_url = f"{base_url}?{params_str}"
```

**Filter Data Format by Widget Type:**

| Widget | Format | Example |
|--------|--------|---------|
| `AutocompleteFilterWidget` | `[{"value": ..., "label": ...}]` | `[{"value": 5, "label": "Tech"}]` |
| `MultipleChoiceFilterWidget` | `[{"value": ..., "label": ...}]` | `[{"value": "draft", "label": "Draft"}]` |
| `ChoiceFilterWidget` | String | `"published"` |
| `BooleanFilterWidget` | Boolean | `True` or `False` |
| `StringFilterWidget` | String | `"search term"` |
| `DateFilterWidget` | String (ISO format) | `"2024-01-15"` |

**Example: Link from Comment to filtered Article list**

```python
# blog/admin.py
from django.shortcuts import redirect
from django.urls import reverse
from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.services.views import SBAdminViewService

from blog.models import Article, Comment

@admin.register(Comment, site=sb_admin_site)
class CommentAdmin(SBAdmin):
    
    def response_change(self, request, obj):
        """After saving a comment, redirect to article list filtered by author."""
        if "_view_author_articles" in request.POST:
            author = obj.article.author
            
            # Build filter with {value, label} format for AutocompleteFilterWidget
            filter_data = {
                "author": [
                    {"value": author.pk, "label": author.name},
                ],
            }
            
            view_id = "blog_article"
            base_url = reverse("sb_admin:blog_article_changelist")
            params_str = SBAdminViewService.build_list_params_url(view_id, filter_data)
            
            return redirect(f"{base_url}?{params_str}")
        
        return super().response_change(request, obj)
```

**Key points:**
- View ID format: `{app_label}_{model_name}` (lowercase, underscore-separated)
- `AutocompleteFilterWidget` and `MultipleChoiceFilterWidget` **require** array format with `value` and `label` keys
- The `label` is displayed in the filter UI; `value` is used for the actual query
- Use `reverse("sb_admin:{app_label}_{model_name}_changelist")` to get the base URL

**Source:** `django_smartbase_admin/services/views.py` - `SBAdminViewService.build_list_params_url`

---

## Detail View Layout (Sidebar)

The detail/change view in SBAdmin supports a two-column layout: main content on the left and a sidebar on the right. Use this for metadata, status info, or secondary fields that shouldn't take up full width.

### Using `DETAIL_STRUCTURE_RIGHT_CLASS`

Add the `DETAIL_STRUCTURE_RIGHT_CLASS` to a fieldset's `classes` to place it in the right sidebar:

```python
from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.engine.const import DETAIL_STRUCTURE_RIGHT_CLASS

@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    readonly_fields = ["created_at", "updated_at", "word_count"]
    
    sbadmin_fieldsets = [
        # Main content (left/center)
        (
            "Content",
            {
                "fields": ["title", "body", "category"],
            },
        ),
        # Sidebar (right)
        (
            "Metadata",
            {
                "fields": ["author", "status", "created_at", "updated_at"],
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
        (
            "Statistics",
            {
                "fields": ["word_count"],
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
    ]
```

### Custom HTML Fields in Sidebar

For rich content like formatted cards, create readonly methods that return HTML. Use `short_description` to set a clean label:

```python
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django_smartbase_admin.engine.const import DETAIL_STRUCTURE_RIGHT_CLASS

@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    readonly_fields = ["title", "body", "category", "status_card"]
    
    sbadmin_fieldsets = [
        (
            "Content",
            {
                "fields": ["title", "body", "category"],
            },
        ),
        (
            None,  # No header for this fieldset
            {
                "fields": ["status_card"],
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
    ]
    
    def status_card(self, obj):
        """Render a status card as HTML."""
        if not obj:
            return "-"
        
        color = {"draft": "warning", "published": "success", "archived": "secondary"}.get(obj.status, "info")
        
        return mark_safe(
            f'<div class="card">'
            f'<div class="card-header fw-bold">{_("Status")}</div>'
            f'<div class="card-body">'
            f'<span class="badge bg-{color}">{escape(obj.status)}</span>'
            f'</div></div>'
        )
    status_card.short_description = _("Status")  # Sets the field label
```

### Hiding Labels (Optional)

The `short_description` sets a reasonable label (e.g., "Status:"). If you want to hide labels entirely for custom HTML fields, override the template:

```html
{# templates/sb_admin/blog/article/change_form.html #}
{% extends "sb_admin/actions/change_form.html" %}

{% block js_init %}
{{ block.super }}
<style>
    /* Hide labels for custom HTML fields */
    label[for="id_status_card"] {
        display: none;
    }
</style>
{% endblock %}
```

Then set `change_form_template` in your admin:

```python
@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    change_form_template = "sb_admin/blog/article/change_form.html"
    # ... rest of config
```

**Note:** This is optional — the default label from `short_description` is usually sufficient.

### Combining with Collapse

Sidebar fieldsets can also be collapsible:

```python
sbadmin_fieldsets = [
    # ... main content ...
    (
        "Advanced Options",
        {
            "fields": ["seo_title", "seo_description"],
            "classes": [DETAIL_STRUCTURE_RIGHT_CLASS, "collapse"],
        },
    ),
]
```

**Key points:**
- Fieldsets are rendered in order - put main content fieldsets first, then sidebar fieldsets
- Use `None` as fieldset title to hide the header entirely
- Import `DETAIL_STRUCTURE_RIGHT_CLASS` from `django_smartbase_admin.engine.const`
- Custom HTML fields need `mark_safe()` and should escape user content with `escape()`
- Sidebar is hidden in modal views (only shown in full page detail view)

**Source:** `django_smartbase_admin/engine/const.py`, `django_smartbase_admin/templates/sb_admin/actions/change_form.html`

---

## Detail View Tabs (`sbadmin_tabs`)

Use `sbadmin_tabs` to organize fieldsets and inlines into separate tabs on the detail/change view. Without tabs, all fieldsets and inlines render on a single page. With tabs, users switch between logical groups.

### Usage

`sbadmin_tabs` is a **dict** where:
- **Keys** are tab label strings (displayed as tab headers)
- **Values** are lists of **fieldset names** and/or **inline classes**

```python
from django.contrib import admin
from django_smartbase_admin.admin.admin_base import SBAdmin, SBAdminTableInline
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.const import DETAIL_STRUCTURE_RIGHT_CLASS

from blog.models import Article, ArticleTag, Comment


class ArticleTagInline(SBAdminTableInline):
    model = ArticleTag
    extra = 0
    verbose_name = "Tag"
    verbose_name_plural = "Tags"


class CommentInline(SBAdminTableInline):
    model = Comment
    extra = 0
    verbose_name = "Comment"
    verbose_name_plural = "Comments"


@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
    model = Article
    inlines = [ArticleTagInline, CommentInline]

    fieldsets = (
        (
            None,
            {
                "fields": ("title", "body", "category"),
            },
        ),
        (
            "Publishing",
            {
                "fields": ("author", "status"),
                "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
            },
        ),
        (
            "SEO Settings",
            {
                "fields": ("seo_title", "seo_description"),
            },
        ),
    )

    sbadmin_tabs = {
        "Content": [None, "Publishing", ArticleTagInline],
        "Comments": [CommentInline],
        "SEO": ["SEO Settings"],
    }
```

### How Tab Keys Map to Content

The template tag resolves each value in the list against two maps:

| Value type | Matched against | Example |
|------------|-----------------|---------|
| Fieldset name (first element of fieldset tuple) | `{fieldset.name: fieldset}` | `None`, `"Publishing"`, `"SEO Settings"` |
| Inline class | `{inline.opts.__class__: inline}` | `ArticleTagInline`, `CommentInline` |

A fieldset with `None` as its name (no header) is referenced as `None` in the tabs dict.

### Fieldset Names Must Be Unique

Because fieldsets are looked up by name, each fieldset must have a **unique** first element. Two fieldsets both named `None` would conflict — only the last one would be found in the lookup.

```python
# ❌ BAD - Two fieldsets with the same name (None)
fieldsets = (
    (None, {"fields": ("title", "body")}),
    (None, {"fields": ("author", "status")}),
)

# ✅ GOOD - Give at least one a name
fieldsets = (
    (None, {"fields": ("title", "body")}),
    ("Status", {"fields": ("author", "status")}),
)
```

### Default Behavior (No Tabs)

When `sbadmin_tabs` is `None` (the default), all fieldsets and inlines render sequentially on a single page — no tab UI is shown.

### Error Handling

When a form has validation errors, the tab containing the error is automatically activated and highlighted so the user sees the problem immediately. If multiple tabs have errors, the first one with errors is shown.

### Combining with Sidebar

Tabs work with `DETAIL_STRUCTURE_RIGHT_CLASS`. A fieldset with the sidebar class renders in the right column **within its tab**:

```python
fieldsets = (
    (
        None,
        {"fields": ("title", "body")},
    ),
    (
        "Metadata",
        {
            "fields": ("author", "status", "created_at"),
            "classes": [DETAIL_STRUCTURE_RIGHT_CLASS],
        },
    ),
    (
        "SEO Settings",
        {"fields": ("seo_title", "seo_description")},
    ),
)

sbadmin_tabs = {
    "Content": [None, "Metadata", ArticleTagInline],
    "SEO": ["SEO Settings"],
}
```

In this example, the "Content" tab has a two-column layout (main fields on the left, metadata sidebar on the right, tags inline below), while the "SEO" tab is a simple single-column form.

**Key points:**
- `sbadmin_tabs` is a `dict`, not a list (the attribute reference table type is approximate)
- Keys are tab labels (strings), values are lists of fieldset names and/or inline classes
- Fieldsets are referenced by their **name** (first element of the tuple) — use `None` for unnamed fieldsets
- Inlines are referenced by their **class** (e.g., `ArticleTagInline`), not by a string
- Every fieldset and inline should appear in exactly one tab — items not listed in any tab are not rendered
- The first tab is active by default (unless there are validation errors in another tab)
- Works with `DETAIL_STRUCTURE_RIGHT_CLASS` for sidebar layout within a tab
- Override `get_sbadmin_tabs(request, object_id)` for dynamic tab configuration

**Source:** `django_smartbase_admin/admin/admin_base.py` — `SBAdmin.sbadmin_tabs`, `get_sbadmin_tabs()`, `get_tabs_context()`; `django_smartbase_admin/templatetags/sb_admin_tags.py` — `get_tabular_context()`

---

## Logo Customization

Override default logo by placing files in your static directory:
- `static/sb_admin/images/logo.svg` - Light mode
- `static/sb_admin/images/logo_light.svg` - Dark mode

---

## URL-Callable Action Methods (`@sbadmin_action`)

Mark view methods as URL-callable with `@sbadmin_action`. All URL-routed actions go through `delegate_to_action`, which checks for this decorator and runs `has_permission_for_action` before dispatching.

### Usage

```python
from django.contrib import admin
from django.http import JsonResponse
from django_smartbase_admin.admin.admin_base import SBAdmin
from django_smartbase_admin.admin.site import sb_admin_site
from django_smartbase_admin.engine.actions import SBAdminCustomAction, sbadmin_action

from blog.models import Article


# ❌ BAD — method is not decorated, returns 404 when called via URL
@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
 def action_custom_export(self, request, modifier):
 return JsonResponse({"status": "exported"})

 def get_sbadmin_list_actions(self, request):
 return [
 SBAdminCustomAction(
 title="Export", view=self, action_id="action_custom_export"
 ),
 ]


# ✅ GOOD — method is decorated
@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
 @sbadmin_action
 def action_custom_export(self, request, modifier):
 return JsonResponse({"status": "exported"})

 def get_sbadmin_list_actions(self, request):
 return [
 SBAdminCustomAction(
 title="Export", view=self, action_id="action_custom_export"
 ),
 ]


# ✅ GOOD — decorator with keyword arguments
@admin.register(Article, site=sb_admin_site)
class ArticleAdmin(SBAdmin):
 @sbadmin_action(permission="delete")
 def action_bulk_archive(self, request, modifier):
 ...
```

**Key points:**
- Import from `django_smartbase_admin.engine.actions`
- All built-in action methods (`action_list_json`, `action_autocomplete`, `action_config`, etc.) are already decorated
- `SBAdminFormViewAction` modal views (see [Selection Actions](#selection-actions-bulk-actions)) are automatically marked — no decorator needed
- `SBAdminCustomAction` with direct `action_id` (via `get_sbadmin_list_actions` or `get_sbadmin_list_selection_actions`) requires the decorator on the target method
- Subclasses that override decorated methods inherit the marker
- `delegate_to_action` checks `has_permission_for_action` for every dispatched action, which delegates to `SBAdminRoleConfiguration.has_permission()` (see [Custom Permission System](#custom-permission-system-has_permission))

**Source:** `django_smartbase_admin/engine/actions.py` — `sbadmin_action`; `django_smartbase_admin/services/views.py` — `SBAdminViewService.delegate_to_action`

---

## SBAdmin Attribute Reference

Quick reference for all `sbadmin_` prefixed class attributes available in `SBAdmin` and related classes.

### List View Attributes (SBAdmin)

| Attribute | Type | Description |
|-----------|------|-------------|
| `sbadmin_list_display` | tuple | Define columns using `SBAdminField` or field names |
| `sbadmin_list_display_data` | tuple | Field names always fetched (even if column hidden) |
| `sbadmin_list_filter` | tuple | Default visible filters - accepts `SBAdminField` names |
| `sbadmin_list_view_config` | list[dict] | Pre-filtered view tabs configuration |
| `sbadmin_list_selection_actions` | list | Custom bulk actions (override `get_sbadmin_list_selection_actions()`) |
| `sbadmin_list_actions` | list | List-level actions (not selection-based) |
| `sbadmin_list_reorder_field` | str | Field name for drag-and-drop row reordering |
| `sbadmin_xlsx_options` | dict | Excel export configuration options |
| `sbadmin_table_history_enabled` | bool | Enable/disable table state history (default: `True`) |

### Detail/Change View Attributes (SBAdmin)

| Attribute | Type | Description |
|-----------|------|-------------|
| `sbadmin_fieldsets` | tuple | Custom fieldset configuration for change form |
| `sbadmin_tabs` | dict | Organize fieldsets and inlines into tabs (see [Detail View Tabs](#detail-view-tabs-sbadmin_tabs)) |
| `sbadmin_detail_actions` | list | Actions shown on detail/change page |
| `sbadmin_previous_next_buttons_enabled` | bool | Show prev/next navigation buttons (default: `False`) |
| `sbadmin_is_generic_model` | bool | Mark as generic model for special handling (default: `False`) |

### Inline Attributes (SBAdminTableInline/SBAdminStackedInline)

| Attribute | Type | Description |
|-----------|------|-------------|
| `sbadmin_fake_inlines` | list | Additional inline classes to include |
| `sbadmin_sortable_field_options` | list | Field names for inline row ordering (default: `["order_by"]`) |
| `sbadmin_inline_list_actions` | list | Actions available for inline rows |

**Source:** `django_smartbase_admin/engine/admin_base_view.py`, `django_smartbase_admin/admin/admin_base.py`

---

## Audit Logging

Built-in optional app that automatically tracks all admin operations (create, update, delete, bulk) with field-level diffs, object snapshots, and request grouping. Works by patching Django's `Model.save()`, `Model.delete()`, `QuerySet.update()`, `QuerySet.delete()`, `QuerySet.bulk_create()`, and `QuerySet.bulk_update()` — only active inside SBAdmin request context.

### Installation

1. Add to `INSTALLED_APPS` (after `django_smartbase_admin`):

```python
INSTALLED_APPS = [
    # your apps...
    "django_smartbase_admin",
    "django_smartbase_admin.audit",
]
```

2. Run migrations:

```bash
python manage.py migrate
```

3. Add to your menu in `sbadmin_config.py`:

```python
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.audit.models import AdminAuditLog

_role_config = SBAdminRoleConfiguration(
    menu_items=[
        # ... other menu items ...
        SBAdminMenuItem(
            label="Audit Log",
            icon="Time",
            view_id=SBAdminViewService.get_model_path(AdminAuditLog),
        ),
    ],
    # ...
)
```

The admin view is auto-registered by the audit app — no `@admin.register` needed.

### What Gets Recorded

Each `AdminAuditLog` entry contains:

| Field | Description |
|-------|-------------|
| `timestamp` | When the change happened |
| `user` | Who made the change |
| `request_id` | UUID grouping all changes from the same request |
| `content_type` + `object_id` | The changed object |
| `object_repr` | String representation of the object |
| `action_type` | `create`, `update`, `delete`, `bulk_create`, `bulk_update`, `bulk_delete` |
| `snapshot_before` | Full object state before the change (JSON) |
| `changes` | Field-level diffs: `{"field": {"old": ..., "new": ..., "old_display": ..., "new_display": ...}}` |
| `parent_content_type` + `parent_object_id` | Parent object context (for inline edits) |
| `affected_objects` | FK targets referenced in changes (JSON array) |
| `is_bulk` / `bulk_count` | Whether it was a bulk operation and how many items |

### Skipping Models and Fields

By default, the audit app skips `admin.LogEntry`, `sessions.Session`, and `contenttypes.ContentType`. It also skips `auto_now` / `auto_now_add` fields and `last_login` on `auth.User`.

Add project-specific skip rules in `settings.py`:

```python
# Skip entire models from auditing
SB_ADMIN_AUDIT_SKIP_MODELS = {
    ("blog", "comment"),  # (app_label, model_name) tuples
}

# Skip specific fields per model
SB_ADMIN_AUDIT_SKIP_FIELDS = {
    ("blog", "article"): {"internal_score", "cache_key"},
}
```

### History Button — Detail View (Object History)

When `django_smartbase_admin.audit` is in `INSTALLED_APPS`, the "History" button on any detail page **automatically** redirects to the audit log filtered for that object. No mixin or per-model configuration is needed — it's built into `SBAdmin.history_view()`.

When a user clicks "History" on an Article detail page, they are redirected to the audit log filtered to show all changes for that specific article (including inline/related changes).

### History Button — List View (Model History)

When `django_smartbase_admin.audit` is in `INSTALLED_APPS`, a "History" button **automatically** appears on every model's list view. Clicking it redirects to the audit log filtered by that model's content type, showing all changes for that model.

**Disabling for specific models:**

Set `sbadmin_list_history_enabled = False` on any admin class to hide the History button from its list view:

```python
@admin.register(Comment, site=sb_admin_site)
class CommentAdmin(SBAdmin):
    sbadmin_list_history_enabled = False  # No History button on list view
```

The audit log admin itself automatically disables this to avoid circular navigation.

### Programmatic Audit Entries (`_create_audit_log`)

For custom actions that call external APIs or perform operations outside Django's ORM (where automatic auditing doesn't apply), create audit log entries manually using `_create_audit_log`.

**Use case:** A bulk "Publish" action calls an external CMS API. The ORM is not involved, so automatic auditing doesn't capture the change. Create entries manually so the audit trail is complete.

```python
import logging

from django_smartbase_admin.audit.manager import _create_audit_log

from blog.models import Article

logger = logging.getLogger(__name__)


def _audit_publish_action(articles: list[dict], published_by: str) -> None:
    """Create one audit log entry per article for an external publish action."""
    for article in articles:
        try:
            _create_audit_log(
                action_type="update",
                model=Article,
                object_id=str(article["id"]),
                object_repr=f"Publish: {article['title']}",
                changes={
                    "status": {"old": "draft", "new": "published"},
                    "published_by": {"old": None, "new": published_by},
                    "author": {"old": None, "new": article["author_name"]},
                },
                affected_objects=[
                    {"ct": "blog.author", "id": article["author_id"], "repr": article["author_name"]},
                    {"ct": "blog.category", "id": article["category_id"], "repr": article["category_name"]},
                ],
            )
        except Exception:
            logger.exception("Failed to create audit log for article #%s", article["id"])
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action_type` | str | Yes | `"create"`, `"update"`, `"delete"`, `"bulk_create"`, `"bulk_update"`, `"bulk_delete"` |
| `model` | Model class | Yes | The Django model class |
| `object_id` | str | No | Primary key of the affected object (as string) |
| `object_repr` | str | No | Human-readable description shown in the audit log |
| `snapshot_before` | dict | No | Full object state before the change (JSON-serializable) |
| `changes` | dict | No | Field-level diffs: `{"field": {"old": ..., "new": ...}}` |
| `is_bulk` | bool | No | Whether this is a bulk operation |
| `bulk_count` | int | No | Number of affected items in bulk operation |
| `affected_objects` | list | No | Related objects: `[{"ct": "app_label.model_name", "id": pk, "repr": "display name"}]` |

**Key points:**
- The `user` field is automatically populated from the current request via `SBAdminThreadLocalService`
- The `request_id` is automatically populated, grouping all entries from the same request
- Wraps in `transaction.atomic()` so audit failures never break the main transaction
- Use for external API calls, cross-service operations, or any action not captured by ORM patching
- For bulk operations, you can create one entry per item (individually traceable) or one summary entry with `is_bulk=True`
- The `ct` in `affected_objects` uses format `"app_label.model_name"` (lowercase)

### Programmatic Audit URLs

Generate audit history URLs from Python code (e.g., for links or redirects):

```python
from django_smartbase_admin.audit.views import get_audit_history_url, get_audit_model_history_url

# Get URL to audit history for a specific object
article = Article.objects.get(pk=42)
url = get_audit_history_url(article)
# Returns: /sb-admin/sb_admin_audit/adminauditlog/?params=...

# Get URL to audit history for an entire model
from blog.models import Article
url = get_audit_model_history_url(Article)
# Returns: /sb-admin/sb_admin_audit/adminauditlog/?params=... (filtered by content_type)
```

### How Auditing Works

The audit app patches Django's ORM methods at startup (`AppConfig.ready()`):

| Method | What it captures |
|--------|-----------------|
| `Model.save()` | Create (new object) or update (existing object) with full diff |
| `Model.delete()` | Delete with full snapshot before |
| `QuerySet.update()` | Single update (with diff) or bulk update (with aggregated changes) |
| `QuerySet.delete()` | Single delete or bulk delete |
| `QuerySet.bulk_create()` | Bulk create with count and IDs |
| `QuerySet.bulk_update()` | Bulk update with aggregated before/after |

**Key behaviors:**
- Only audits inside SBAdmin request context (uses `SBAdminThreadLocalService`)
- Never audits the `AdminAuditLog` model itself (prevents infinite recursion)
- Uses `transaction.atomic()` so audit failures never break the main transaction
- Groups all changes in a single request via `request_id` (stored on the request object)
- Auto-detects parent context from SBAdmin's `request_data` (for inline edits)
- Captures FK display values (`old_display`, `new_display`) for human-readable diffs
- M2M changes are tracked via the through/junction table (create/delete on junction rows)

### Access Control

The audit log access control is implemented in `AdminAuditLogAdmin.get_queryset()` and `_apply_restricted_queryset_for_filters()`. The full logic flow:

**Step 1 — User-based filtering (`get_queryset`):**

| User type | No filter active (global view) | `object_history` filter active | `content_type` filter active |
|-----------|-------------------------------|-------------------------------|------------------------------|
| **Superuser** | All entries | All entries | All entries |
| **Non-superuser** | Own entries only (`user=request.user`) | All users' entries (filter skipped) | Own entries only (`user=request.user`) |

**Step 2 — Restricted queryset permissions (`_apply_restricted_queryset_for_filters`):**

Applies **after** Step 1, for **all users** (including superusers). When `content_type` or `object_history` filters are active:

1. Collects content type IDs from active `object_history` and/or `content_type` filters
2. For each content type, calls `SBAdminViewService.get_restricted_queryset()` on the target model — this invokes the project's `restrict_queryset` from `SBAdminRoleConfiguration`
3. Filters audit entries so only entries with `object_id` in the restricted queryset are shown
4. Entries for non-filtered content types (e.g., parent context, affected objects in the same audit view) are **not** restricted
5. If the model class is unknown or restriction fails → entries for that content type are **excluded** (fail-closed)

**Result by scenario:**

| User type | Global view | Object history (History button on detail) | Model history (History button on list) |
|-----------|------------|------------------------------------------|---------------------------------------|
| **Superuser** | All entries | Entries for that object, restricted by `restrict_queryset` | Entries for that model, restricted by `restrict_queryset` |
| **Non-superuser** | Own entries only | All users' entries for that object, restricted by `restrict_queryset` | Own entries for that model, restricted by `restrict_queryset` |

**Example:** If `restrict_queryset` limits `Article` to published articles only, a non-superuser clicking "History" on the Article list view will see only their own audit entries for published articles — not drafts, and not other users' entries.

Projects can further restrict access by:
- Not adding the audit log `SBAdminMenuItem` for non-admin roles
- Overriding `has_permission` in the role configuration to deny access to the `AdminAuditLog` model
- Overriding `restrict_queryset` to apply additional filters on `AdminAuditLog` itself

---

## Testing

### Setup

Tests use SQLite in-memory and Django's built-in `auth.User` / `Group` models — no external database required.

Install test dependencies into the project virtualenv:

```bash
source .venv/bin/activate
pip install -e .
```

The virtualenv already has all runtime dependencies. No extra test-only packages are needed — tests use `unittest` and Django's built-in test runner.

### Running Tests

```bash
source .venv/bin/activate

# All tests
python runtests.py

# Audit tests only
python runtests.py django_smartbase_admin.audit.tests

# Specific test class
python runtests.py django_smartbase_admin.audit.tests.test_audit_integration.TestAdminCRUD

# Specific test method
python runtests.py django_smartbase_admin.audit.tests.test_audit_integration.TestAdminCRUD.test_create_logs_new_values
```

### Test Structure

| File | What it tests |
|------|---------------|
| `src/django_smartbase_admin/audit/tests/test_diff.py` | Unit tests for `compute_diff`, `compute_bulk_diff`, `compute_bulk_snapshot` |
| `src/django_smartbase_admin/audit/tests/test_audit_integration.py` | Integration tests for audit logging (CRUD, bulk ops, inlines, M2M, request grouping) |
| `tests/settings.py` | Minimal Django settings for standalone test runs |
| `runtests.py` | Test runner entry point |

### Adding New Tests

1. Place test files in `src/django_smartbase_admin/audit/tests/`
2. Use `BaseAuditTest` from `test_audit_integration.py` as base class (installs/uninstalls manager hooks)
3. Use `MockSBAdminContext` and `NoAdminContext` context managers for SBAdmin request simulation
4. Tests use `TransactionTestCase` because audit hooks patch `Model.save()` / `QuerySet.update()` globally

---

## SBAdminWizardView

Multi-step wizard **outside** the `change_form`. The view is a thin dispatcher — each step owns its form/formset creation, validation, context building, and save logic.

### Architecture

- **`SBAdminWizardView`** (`TemplateView` + `SBAdminView`) — holds the ordered step classes, dispatches `get()`/`post()` to the current step, builds base context.
- **`SBAdminWizardStep`** — one step per class. The wizard instantiates a new step object per request. Steps define `title`, `model`, `form_class`, `formset_classes`, and override lifecycle hooks.

### SBAdminWizardStep — Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `title` | str | Step title shown in the template |
| `heading` | str \| None | Heading above the step title. Falls back to `wizard.wizard_step_heading`, then `model._meta.verbose_name` |
| `model` | Model class | **Required**. Used for permission checks |
| `form_class` | Form class | Main form for the step |
| `formset_classes` | list[type[BaseFormSet]] | Formset factory classes. Used for autocomplete widget registration |
| `requires_wizard_object` | bool | If `True`, missing wizard object redirects to step 1 |
| `template_name` | str \| None | Override the default wizard template for this step |
| `submit_button_label` | str \| None | Custom submit button text. `None` = "Next step" / "Finish" |

### SBAdminWizardStep — Methods

| Method | Description |
|--------|-------------|
| `get_form_kwargs(**kwargs)` | Returns kwargs for the main form. Default includes `request` and `view=wizard`. Override to add `instance` |
| `get_form(data, files)` | Creates the main form instance. Bound when `data` is provided |
| `get_formsets(data, files)` | Returns `[(title, formset_instance), ...]`. Override to declare formsets. On GET `data` is `None` |
| `get_context_data(context, **kwargs)` | Builds step-specific template context. Formsets are auto-injected into `wizard_formsets` |
| `form_valid(form, formsets)` | Called after successful validation. **Must return `HttpResponse`**. Raises `NotImplementedError` by default |
| `form_invalid(form, formsets)` | Re-renders the page with bound form/formsets and errors |
| `get_blocked_get_response()` | Return a redirect to block entry to this step (e.g. pending background tasks) |
| `adjust_navigation(nav)` | Modify `back_url`, `wizard_footer_back_url`, `prev_step_url` dict |
| `check_permission(request)` | Raises `PermissionDenied`. Default: `requires_wizard_object` → check *change*, otherwise *add* |

### Step Lifecycle

**GET:**

```
get() → get_blocked_get_response() → _check_requires_wizard_object()
     → get_form() → wizard.get_context_data() → step.get_context_data()
     → get_formsets() injected into context → render
```

**POST:**

```
post() → _check_requires_wizard_object()
      → get_form(POST) + get_formsets(POST)
      → validate all → form_valid(form, formsets)
                     OR form_invalid(form, formsets)
```

### SBAdminWizardView — Required

| Attribute / Method | Description |
|--------------------|-------------|
| `wizard_steps` | Tuple of `SBAdminWizardStep` classes |
| `build_wizard_url(step, object_id=None)` | Returns URL with `?step=N` for the given step |
| `get_wizard_object()` | Returns the wizard's current object from session (or `None`) |
| `update_object_wizard_state(obj, step, completed)` | Persists the wizard progress on the object |

### Example

```python
from django import forms
from django.forms import formset_factory
from django.http import HttpResponseRedirect
from django.urls import reverse

from django_smartbase_admin.admin.admin_base import SBAdminBaseForm, SBAdminBaseFormInit
from django_smartbase_admin.admin.widgets import SBAdminAutocompleteWidget
from django_smartbase_admin.views.sbadmin_wizard_step import SBAdminWizardStep
from django_smartbase_admin.views.sbadmin_wizard_view import SBAdminWizardView

from blog.models import Article, Tag


# -- Step 1: create the article --

class ArticleStep1Form(SBAdminBaseForm):
    class Meta:
        model = Article
        fields = ("title", "category")


class ArticleStep1(SBAdminWizardStep):
    title = "Basic Info"
    model = Article
    form_class = ArticleStep1Form

    def form_valid(self, form, formsets):
        obj = form.save()
        self.wizard.update_object_wizard_state(obj, step=1, completed=False)
        return HttpResponseRedirect(self.wizard.build_wizard_url(2, obj.pk))


# -- Step 2: assign tags via formset --

class TagRowForm(SBAdminBaseFormInit, forms.Form):
    tag = forms.ModelChoiceField(
        queryset=Tag.objects.all(),
        widget=SBAdminAutocompleteWidget(
            model=Tag, multiselect=False,
            label_lambda=lambda request, item: item.name,
        ),
    )

TagRowFormSet = formset_factory(TagRowForm, extra=1, can_delete=True)


class ArticleStep2(SBAdminWizardStep):
    title = "Tags"
    model = Article
    form_class = ArticleStep1Form
    formset_classes = [TagRowFormSet]
    requires_wizard_object = True

    def get_form_kwargs(self, **kwargs):
        kwargs = super().get_form_kwargs(**kwargs)
        kwargs["instance"] = self.wizard.get_wizard_object()
        return kwargs

    def get_formsets(self, data=None, files=None):
        kwargs = {
            "prefix": "tags",
            "form_kwargs": {"view": self.wizard, "request": self.request},
        }
        if data is not None:
            kwargs["data"] = data
        return [("Tags", TagRowFormSet(**kwargs))]

    def form_valid(self, form, formsets):
        article = self.wizard.get_wizard_object()
        fs = formsets[0][1]
        # ... save tag associations from fs.cleaned_data ...
        self.wizard.update_object_wizard_state(article, step=2, completed=True)
        return HttpResponseRedirect("...")


# -- Wizard view --

class ArticleWizard(SBAdminWizardView):
    wizard_steps = (ArticleStep1, ArticleStep2)

    def build_wizard_url(self, step, object_id=None):
        url = reverse("sb_admin:blog_article_wizard")
        return f"{url}?step={step}"
```

Register in `SBAdminRoleConfiguration.registered_views`:

```python
# blog/sbadmin_config.py
from django_smartbase_admin.engine.configuration import SBAdminConfigurationBase, SBAdminRoleConfiguration
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView

from blog.wizard_views import ArticleWizard

_role_config = SBAdminRoleConfiguration(
    default_view=SBAdminMenuItem(view_id="dashboard"),
    menu_items=[
        SBAdminMenuItem(label="Dashboard", icon="All-application", view_id="dashboard"),
        SBAdminMenuItem(label="Articles", icon="Box", view_id="blog_article"),
    ],
    registered_views=[
        SBAdminDashboardView(widgets=[], title="Dashboard"),
        ArticleWizard(title="Create Article"),
    ],
)

class SBAdminConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        return _role_config
```

The wizard view is automatically routed via `view_map` — no manual URL registration needed.

### Formsets in Steps

Steps declare formsets via `get_formsets()` which returns `[(title, formset_instance), ...]`. The base class handles:

- **Context injection**: formsets are automatically added to `wizard_formsets` in the template context
- **Multipart detection**: `form_is_multipart` is set if any form or formset form has file fields
- **POST validation**: all formsets are validated alongside the main form; on failure, `form_invalid` re-renders with bound formsets and errors
- **Autocomplete registration**: `formset_classes` are iterated during `register_autocomplete_views` to instantiate each formset's row form class for widget initialization

**Key points:**
- `formset_classes` is used **only** for autocomplete widget registration (happens during `init_view_dynamic` when no wizard object is available)
- `get_formsets()` is used for actual formset **instance creation** (happens per-request with full wizard state)
- Row forms should extend `SBAdminBaseFormInit` for autocomplete widgets to work
- Pass `form_kwargs={"view": self.wizard, "request": self.request}` when creating formset instances

### Navigation

- **`back_url`** (top arrow): if a wizard object exists in session and the user has `change` permission, points to the object's **change** page; otherwise points to the changelist.
- **`wizard_footer_back_url`**: on step > 1, points to the previous wizard step; on step 1 with an existing object, points to the **change** page (same as the arrow); otherwise the footer "Back" button is hidden.
- Override `adjust_navigation(nav)` on the step to customize these URLs.

### Template

Default template: `sb_admin/wizard/wizard_step.html`

| Context variable | Description |
|-----------------|-------------|
| `wizard_heading` | Heading from `step.get_heading()` |
| `sbadmin_wizard_step_title` | Step title |
| `sbadmin_wizard_submit_label` | Submit button text |
| `wizard_formsets` | List of `(title, formset)` tuples |
| `form_is_multipart` | `True` if any form has file fields |
| `wizard_primary_section_title` | Optional title above the main form fields |
| `sbadmin_wizard_step_banner` | Optional HTML banner shown at the top of the step |
| `sbadmin_wizard_poll_seconds` | If set, the page auto-refreshes at this interval |

**Formset rendering in the template**: each formset in `wizard_formsets` is rendered inside a `.sbadmin-formset-dynamic` wrapper with `data-prefix` and `data-max-forms`. Rows live in `.sbadmin-formset-forms`. If the formset allows adding rows, a `<template>` with the empty form and a `.sbadmin-formset-add` button are rendered. The script `sb_admin/js/sbadmin_formset.js` clones the template row, replaces `__prefix__` in attributes, increments `TOTAL_FORMS`, and fires `formset:added` on the new row element (matching Django's native event, used by autocomplete and other SBAdmin widgets to re-initialize).


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
