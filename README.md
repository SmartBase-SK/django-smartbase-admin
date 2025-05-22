# Django SmartBase Admin

A modern, modular, and developer-friendly admin interface for Django.  
Built to **speed up development** of internal tools and admin panels — beautifully and efficiently.

---

## ✨ Features
- Fast integration with any Django project
- Improved performance of Django List Admin using `SBAdminField`, database `annotate()` and `values()` to avoid direct object access  
- Simple configuration of menu structure, dashboard components, and permissions per user role  
- Enhanced Django List Admin filters: autocomplete support for related fields and filtering across all model fields  
- Ability for users to save and reuse custom filters in Django List Admin  
- Improved Django Detail Admin with autocomplete for relational fields  
- Support for "FakeInlines" – define inline-like blocks without requiring a direct model relationship  
- Easy extension of list and detail views with custom actions and corresponding views
- Beautiful modern UI (Tailwind CSS)
- Responsive & mobile-friendly

![image](https://github.com/user-attachments/assets/b99a35b0-05fd-45e3-a165-950b0d4750cd)
![image](https://github.com/user-attachments/assets/f7719377-eb88-42c4-8fe0-5d4ca0ff29bf)


## 📚 Full Documentation (in progress)

🗂 [View Full Docs](https://smartbase-sk.github.io/django-smartbase-admin-docs/docs/installation)

## ⚡ Quick Start

### 1. Install Smartbase Admin

Begin by installing the Smartbase Admin package using `pip`:

```bash
pip install django-smartbase-admin
```

Ensure that django-smartbase-admin and its dependencies are included in your Django settings. Open your `settings.py` file and add the following to `INSTALLED_APPS`:
```python
INSTALLED_APPS = [
    # other apps
    "django_smartbase_admin",
    "easy_thumbnails",
    "widget_tweaks",
]
```

### 2. Add Admin URL Configuration
In your project’s `urls.py`, register the Smartbase Admin site by importing sb_admin_site and adding the path:
```python
from django_smartbase_admin.admin.site import sb_admin_site

urlpatterns = [
    path("sb-admin/", sb_admin_site.urls),
    # other paths
]
```
This makes the Smartbase Admin interface accessible at `/sb-admin/`

### 3. Define the SmartBase Admin Configuration
In your project, for example in `config` package create a file called `sbadmin_config.py` with the following content:
```python
from django_smartbase_admin.engine.configuration import SBAdminConfigurationBase, SBAdminRoleConfiguration
from django_smartbase_admin.views.dashboard_view import SBAdminDashboardView
from django_smartbase_admin.engine.menu_item import SBAdminMenuItem

config = SBAdminRoleConfiguration(
    default_view=SBAdminMenuItem(view_id="dashboard"),
    menu_items=[
        SBAdminMenuItem(view_id="dashboard", icon="All-application"),
    ],
    registered_views=[
        SBAdminDashboardView(widgets=[], title="Dashboard"),
    ],
)

class SBAdminConfiguration(SBAdminConfigurationBase):
    def get_configuration_for_roles(self, user_roles):
        return config
```

### 4. Reference the Configuration in `settings.py`
```python
SB_ADMIN_CONFIGURATION = "config.sbadmin_config.SBAdminConfiguration"
```

### 5. Add Locale Middleware
Add the following middleware to support internationalization:
```python
MIDDLEWARE = [
    # Other middleware...
    'django.middleware.locale.LocaleMiddleware',
]
```

##  🤝 Need Help with Development?
We at SmartBase are experts in Django and custom software.

Whether you're building a new platform or modernizing an internal tool —
💡 We can help you design, build, and scale it.

📬 [Let’s talk](https://en.smartbase.sk/contact-us/) — We’d love to work with you.
