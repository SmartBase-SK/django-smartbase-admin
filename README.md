<img alt="image" src="https://github.com/user-attachments/assets/b0d5537f-29c4-46ca-b514-9862b26cb000"/>

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
- End-user ready for building SaaS or similar projects with global queryset configuration
<img alt="image" src="https://github.com/user-attachments/assets/ebbcacea-9052-409e-99bb-9f9e0804bbc5" />
<img alt="image" src="https://github.com/user-attachments/assets/8003df6a-e035-4c8f-8e90-0e710818d33e" />
<img alt="image" src="https://github.com/user-attachments/assets/29e116de-a8c6-4f22-8485-3e0eba5ed564" />
<img alt="image" src="https://github.com/user-attachments/assets/46aefe59-e49c-4483-ba1f-eb18397db6ae" />
<img alt="image" src="https://github.com/user-attachments/assets/ea354dcb-b4a9-47af-8046-ba0d55d72746" />
<img alt="image" src="https://github.com/user-attachments/assets/10a5d75c-ae3e-4e2b-aeb2-e943e6363a2f" />
<img alt="image" src="https://github.com/user-attachments/assets/3e6bfdbb-0c07-4fad-96f0-552cbcc9d4ae" />
<img alt="image" src="https://github.com/user-attachments/assets/b3acd00b-c425-4e5f-b113-97215bb85157" />
<img alt="image" src="https://github.com/user-attachments/assets/dc5f3f80-3325-4f5d-acec-236d6b241a7f" />
<img alt="image" src="https://github.com/user-attachments/assets/216d4e50-5af4-4e57-8649-1211a82f493e" />
<img alt="image" src="https://github.com/user-attachments/assets/167461dd-ec2e-4327-a208-4014f42100f9" />
<img alt="image" src="https://github.com/user-attachments/assets/3871e505-1bc9-4a6c-8457-4ad363a582af" />


## 📚 Full Documentation (in progress)

🗂 [View Full Docs](https://smartbase-sk.github.io/django-smartbase-admin-docs/docs/installation)


## 🌐 Live Demo

Want to see it in action?  
👉 [Check out the live demo](https://sbadmin.sbdev.sk/)  

**Login credentials:**
- **Admin role**: `admin / admin`  
- **Editor role**: `editor / editor`  



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
    "ckeditor",
    "ckeditor_uploader",
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

## 🤖 AI/Developer Reference

See [AGENTS.md](./AGENTS.md) for development patterns, gotchas, and AI assistant instructions.

##  🤝 Need Help with Development?
We at SmartBase are experts in Django and custom software.

Whether you're building a new platform or modernizing an internal tool —
💡 We can help you design, build, and scale it.

📬 [Let's talk](https://en.smartbase.sk/contact-us/) — We'd love to work with you.
