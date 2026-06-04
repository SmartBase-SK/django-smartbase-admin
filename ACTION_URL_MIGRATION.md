# SBAdmin Action URL Migration

This guide is for projects upgrading to the SBAdmin action URL contract where every
URL-routed action receives:

```python
action_function(request, modifier, object_id)
```

The action URL shape is now always:

```python
<view>/<action>/<modifier>/
<view>/<action>/<modifier>/<object_id>/
```

`modifier` and `object_id` are separate values. Row and detail actions no longer pass
the row primary key through `modifier`.

## What Changed

- Every `@sbadmin_action` method must accept `request, modifier, object_id`.
- Row method actions receive `modifier="template"` and the row pk in `object_id`.
- Detail, fieldset, inline, and row modal actions receive the current object pk in
  `object_id`.
- List and selection actions usually receive `object_id=None`.
- Dynamic-region actions keep their real modifier, such as `"add"`, and pass the edit
  object through the optional `object_id` segment.
- `MODIFIER_OBJECT_ID` is no longer an action modifier sentinel.
- `MODIFIER_OBJECT_ID` is still valid inside direct URL strings that need row-pk
  replacement.

## Search Checklist

Run these searches in consumer projects:

```bash
rg -n "@sbadmin_action|def action_|action_modifier=MODIFIER_OBJECT_ID|MODIFIER_OBJECT_ID|SBAdminRowAction|SBAdminFormViewAction|RowActionModalView|ActionModalView"
```

Then update these cases:

- `def action_x(self, request, modifier)` to `def action_x(self, request, modifier, object_id)`.
- Any row/detail action that reads `modifier` as a pk to read `object_id`.
- Any direct call to a base action method to pass `object_id` too.
- Any `action_modifier=MODIFIER_OBJECT_ID` on method or modal actions to remove it.
- Any positional `get_action_url("action", object_id)` calls to use
  `get_action_url("action", object_id=object_id)`.

## Row Method Actions

Before, row method actions often treated `modifier` as the row pk:

```python
def get_sbadmin_row_actions(self, request):
    return [
        SBAdminRowAction(
            action_id=ACTION_IMPERSONATE_USER,
            title=_("Impersonate"),
            icon="Login",
            view=self,
        )
    ]


@sbadmin_action(permission="view")
def action_impersonate_user(self, request, modifier):
    post_data = request.POST.copy()
    post_data["user_pk"] = str(modifier)
    request.POST = post_data
    return AcquireUserView.as_view()(request)
```

After, keep `modifier` for action state and read the row pk from `object_id`:

```python
def get_sbadmin_row_actions(self, request):
    return [
        SBAdminRowAction(
            action_id=ACTION_IMPERSONATE_USER,
            title=_("Impersonate"),
            icon="Login",
            view=self,
        )
    ]


@sbadmin_action(permission="view")
def action_impersonate_user(self, request, modifier, object_id):
    post_data = request.POST.copy()
    post_data["user_pk"] = str(object_id)
    request.POST = post_data
    return AcquireUserView.as_view()(request)
```

The generated row URL changes from a pk-as-modifier form to:

```text
/admin-view/action_impersonate_user/template/<row_pk>/
```

## Row Method Actions With Prebuilt URLs

`MODIFIER_OBJECT_ID` can still be used inside a URL string that is materialized per
row.

Before:

```python
SBAdminRowAction(
    url=self.get_action_url(
        ACTION_DOWNLOAD_LABEL,
        object_id=MODIFIER_OBJECT_ID,
    ),
    title=_("Download label"),
    icon="Download",
)


@sbadmin_action
def action_download_label(self, request, modifier):
    document = service.download_label(str(modifier), actor=actor)
    ...
```

After:

```python
SBAdminRowAction(
    url=self.get_action_url(
        ACTION_DOWNLOAD_LABEL,
        object_id=MODIFIER_OBJECT_ID,
    ),
    title=_("Download label"),
    icon="Download",
)


@sbadmin_action
def action_download_label(self, request, modifier, object_id):
    document = service.download_label(str(object_id), actor=actor)
    ...
```

The placeholder is replaced in the URL string before rendering each row. It is not an
action modifier.

## Row And Detail Modal Actions

Before, method and modal actions sometimes used `action_modifier=MODIFIER_OBJECT_ID`
to force pk routing:

```python
SBAdminFormViewAction(
    target_view=PackagePriceAdjustmentView,
    title=_("Adjust price"),
    view=self,
    action_modifier=MODIFIER_OBJECT_ID,
    open_in_modal=True,
)
```

After, remove the modifier override:

```python
SBAdminFormViewAction(
    target_view=PackagePriceAdjustmentView,
    title=_("Adjust price"),
    view=self,
    open_in_modal=True,
)
```

`RowActionModalView.get_object_id()` now reads `object_id`, so row/detail modal views
continue to load the current object through the owning admin queryset.

## Detail Actions And Positional URL Calls

Before, passing the object id as the second positional argument made it the modifier:

```python
SBAdminCustomAction(
    title=_("Approve"),
    url=self.get_action_url("approve", object_id),
)


@sbadmin_action
def approve(self, request, pk):
    obj = self.get_object(request, pk)
    ...
```

After, pass the object id by keyword and keep the three-argument signature:

```python
SBAdminCustomAction(
    title=_("Approve"),
    url=self.get_action_url("approve", object_id=object_id),
)


@sbadmin_action
def approve(self, request, modifier, object_id):
    obj = self.get_object(request, object_id)
    ...
```

## List And Bulk Actions

List and bulk actions still use `modifier` for list selection state, config ids, or
special values such as `"__all__"`. They usually ignore `object_id`.

Before:

```python
@sbadmin_action
def action_bulk_delete(self, request, modifier):
    return super().action_bulk_delete(request, modifier)
```

After:

```python
@sbadmin_action
def action_bulk_delete(self, request, modifier, object_id):
    return super().action_bulk_delete(request, modifier, object_id)
```

## Framework Action Overrides

When overriding built-in SBAdmin action methods, add `object_id` and forward it to
base methods.

Before:

```python
@sbadmin_action
def action_enter_reorder(self, request, modifier):
    if not self.use_tree_ordering:
        return super().action_enter_reorder(request, modifier)
    self.activate_reorder(request)
    return self.action_list(request, tabulator_definition=tabulator_definition)


@sbadmin_action
def action_list_json(self, request, modifier, page_size=None):
    action = self.sbadmin_list_action_class(self, request, page_size=page_size)
    return JsonResponse(data=action.get_json_data(), safe=False)
```

After:

```python
@sbadmin_action
def action_enter_reorder(self, request, modifier, object_id):
    if not self.use_tree_ordering:
        return super().action_enter_reorder(request, modifier, object_id)
    self.activate_reorder(request)
    return self.action_list(
        request,
        modifier,
        object_id,
        tabulator_definition=tabulator_definition,
    )


@sbadmin_action
def action_list_json(self, request, modifier, object_id=None, page_size=None):
    action = self.sbadmin_list_action_class(self, request, page_size=page_size)
    return JsonResponse(data=action.get_json_data(), safe=False)
```

## Manual Modal Dispatch

If an action manually delegates to an `ActionModalView`, pass both route values.

Before:

```python
@sbadmin_action
def fix_email_action(self, request, modifier):
    return ChangeCustomerEmailActionView.as_view(view=self)(request, modifier)
```

After:

```python
@sbadmin_action
def fix_email_action(self, request, modifier, object_id):
    return ChangeCustomerEmailActionView.as_view(view=self)(
        request,
        modifier=modifier,
        object_id=object_id,
    )
```

## Direct Custom URLs

Keep `MODIFIER_OBJECT_ID` only when it is a placeholder inside a URL string:

```python
SBAdminRowAction(
    url=f"/articles/{MODIFIER_OBJECT_ID}/audit/",
    title=_("Audit"),
    icon="History",
)
```

Do not use it as `action_modifier`:

```python
# Bad
SBAdminRowAction(
    action_id="archive",
    view=self,
    action_modifier=MODIFIER_OBJECT_ID,
)

# Good
SBAdminRowAction(
    action_id="archive",
    view=self,
)
```

## Dynamic Regions

If a consumer builds dynamic-region URLs manually, keep the modifier as the region
mode and pass the edit object through `object_id`.

Before:

```text
/admin-view/sbadmin_dynamic_region/<object_pk>/
```

After:

```text
/admin-view/sbadmin_dynamic_region/add/<object_pk>/
```

Add/create forms still use:

```text
/admin-view/sbadmin_dynamic_region/add/
```

## Test Checklist

After migrating a consumer project, run route-level tests for:

- row method actions
- row modal actions
- detail and fieldset modal actions
- list and bulk actions
- direct URL row actions that use `MODIFIER_OBJECT_ID`
- dynamic-region add and edit endpoints
- any MCP action invocation paths, if the project exposes SBAdmin through MCP

Direct service or method tests are not enough. Hit the generated SBAdmin URLs so the
route shape, action registration, permissions, and modal dispatch are all exercised.

## Examples Checked

This guide was written after checking representative action patterns in:

- `/home/vilo/projects/neoship-app`
- `/home/vilo/projects/smartshop_template`

No files in those consumer projects need to be changed as part of the SBAdmin library
change itself, but they are good examples of the migrations projects will need after
upgrading.
