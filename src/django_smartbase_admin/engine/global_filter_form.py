from django import forms


class SBAdminGlobalFilterForm(forms.Form):
    # if field is listed here then empty value of a field
    # disables filtering by this field instead of filtering by None value
    include_all_values_for_empty_fields = None
