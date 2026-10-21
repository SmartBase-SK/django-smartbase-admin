from django import forms
from django.core.exceptions import ValidationError


class LoadedModelChoiceField(forms.ModelChoiceField):
    """``ModelChoiceField`` that resolves a submitted pk through ``loaded_object``
    (objects the request already read) before running the queryset ``.get()``
    Django does for every bound form."""

    def __init__(self, *args, loaded_object=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.loaded_object = loaded_object

    def to_python(self, value):
        if value in self.empty_values:
            return None
        obj = None
        pk = self.queryset.model._meta.pk
        if self.loaded_object is not None and self.to_field_name in (None, pk.name):
            try:
                obj = self.loaded_object(pk.to_python(value))
            except ValidationError:
                pass
        return obj if obj is not None else super().to_python(value)


class LoadedRowsPkFormsetMixin:
    """Resolves each existing row's posted pk from the rows the formset already
    loaded; Django's hidden pk field runs one ``.get()`` per row on every save.
    A pk outside those rows falls back to that lookup."""

    def add_fields(self, form, index):
        super().add_fields(form, index)
        pk_name = self._pk_field.name
        field = form.fields.get(pk_name)
        if type(field) is forms.ModelChoiceField and field.queryset.model is self.model:
            form.fields[pk_name] = LoadedModelChoiceField(
                field.queryset,
                initial=field.initial,
                required=False,
                widget=field.widget,
                loaded_object=self._existing_object,
            )
