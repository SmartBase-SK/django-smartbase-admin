from django.core.exceptions import FieldDoesNotExist, FieldError, ImproperlyConfigured
from django.db.models import (
    Count,
    Value,
    CharField,
    F,
    DateTimeField,
    BooleanField,
    FilteredRelation,
)
from django.db.models.functions import Concat

from django_smartbase_admin.engine.const import ANNOTATE_KEY, Formatter
from django_smartbase_admin.engine.field_formatter import (
    datetime_formatter,
    boolean_formatter,
)
from django_smartbase_admin.engine.filter_widgets import (
    StringFilterWidget,
    BooleanFilterWidget,
    DateFilterWidget,
    AutocompleteFilterWidget,
)
from django_smartbase_admin.services.translations import SBAdminTranslationsService
from django_smartbase_admin.utils import JSONSerializableMixin


class TabulatorFieldOptions(JSONSerializableMixin):
    headerFilter = False
    headerSort = False
    formatterParams = None
    frozen = False
    title = None
    editorParams = None

    def __init__(
        self,
        headerFilter=None,
        headerSort=None,
        formatterParams=None,
        frozen=None,
        title=None,
        editorParams=None,
    ) -> None:
        super().__init__()
        self.headerFilter = headerFilter
        self.headerSort = headerSort
        self.formatterParams = formatterParams
        self.frozen = frozen
        self.title = title
        self.editorParams = editorParams


class XLSXFieldOptions(JSONSerializableMixin):
    title = None
    field = None
    formatter = None

    def __init__(
        self, title: str = None, field: str = None, formatter: Formatter = None
    ) -> None:
        super().__init__()
        self.title = title
        self.field = field
        self.formatter = formatter


class SBAdminField(JSONSerializableMixin):
    view = None
    title = None
    name = None
    # this is name of the field for purposes of communication with Tabulator.columns and ActionList
    # it gets fetched inside .values() call and is used for annotates not to clash with original field
    # defaults to name
    field = None
    # this is name of the field used in .filter() call, it can differ for purposes of annotate if we
    # display different value in annotate than we want to filter
    # defaults to field
    filter_field = None
    model_field = None
    view_method = None
    filter_widget = None
    filter_disabled = None
    list_visible = None
    list_collapsed = None
    annotate = None
    supporting_annotates = None
    auto_created = None
    formatter = None
    tabulator_editor = None
    python_formatter = None
    tabulator_options = None
    xlsx_options = None
    initialized = False

    def __init__(
        self,
        name,
        title=None,
        model_field=None,
        view_method=None,
        filter_field=None,
        filter_widget: "FilterWidget" = None,
        filter_disabled=None,
        annotate=None,
        annotate_function=None,
        supporting_annotates=None,
        list_visible=None,
        list_collapsed=None,
        auto_created=None,
        formatter: Formatter = Formatter.HTML.value,
        tabulator_editor=None,
        python_formatter=None,
        tabulator_options: "TabulatorFieldOptions" = None,
        xlsx_options: "XLSXFieldOptions" = None,
    ) -> None:
        super().__init__()
        self.title = title
        self.name = name
        self.model_field = model_field
        self.view_method = view_method
        self.filter_field = filter_field
        self.filter_widget = filter_widget
        self.filter_disabled = filter_disabled or self.filter_disabled or False
        self.annotate = annotate
        self.annotate_function = annotate_function
        self.supporting_annotates = supporting_annotates
        self.list_visible = (
            list_visible
            if (list_visible is not None)
            else (self.list_visible if self.list_visible is not None else True)
        )
        self.list_visible_arg = list_visible
        self.list_collapsed = list_collapsed or self.list_collapsed or False
        self.auto_created = auto_created or self.auto_created or False
        self.formatter = formatter
        self.tabulator_editor = tabulator_editor
        self.python_formatter = python_formatter
        self.tabulator_options = tabulator_options
        self.xlsx_options = xlsx_options

    def init_filter_for_field(self, configuration):
        filter_widget = getattr(self, "filter_widget", None)
        if self.filter_disabled:
            return
        if not filter_widget and getattr(self, "model_field", False):
            filter_widget = StringFilterWidget.apply_to_field(self)
            filter_widget = filter_widget or BooleanFilterWidget.apply_to_field(self)
            filter_widget = filter_widget or DateFilterWidget.apply_to_field(self)
            filter_widget = filter_widget or AutocompleteFilterWidget.apply_to_field(
                self
            )
        if not filter_widget:
            filter_widget = StringFilterWidget()
        filter_widget = configuration.get_filter_widget(self, filter_widget)
        if filter_widget:
            filter_widget.init_filter_widget_static(self, self.view, configuration)
            self.filter_widget = filter_widget

    def get_model_field_from_model(self, name):
        if not name:
            return None
        model_field = None
        try:
            model_field = self.view.model._meta.get_field(name)
        except FieldDoesNotExist:
            try:
                model_field = SBAdminTranslationsService.get_field_from_model(
                    self.view.model, name
                )
            except FieldError:
                pass
            pass
        return model_field

    def init_field_static(self, view, configuration):
        self.view = view
        view_method = getattr(self.view, self.name, None)
        if not self.model_field and view_method and callable(view_method):
            self.view_method = view_method
            field_name = getattr(self.view_method, "admin_order_field", None)
            field_description = getattr(
                self.view_method, "short_description", self.title or self.name
            )
            if field_name:
                self.model_field = self.get_model_field_from_model(field_name)
            if field_description:
                self.title = field_description
            if not self.annotate and not self.model_field:
                raise ImproperlyConfigured(
                    f"@admin.display(ordering=...) annotation or SBAdminField with 'annotate' is required for method field '{self.name}' in '{self.view}'."
                )
            if self.model_field and not self.annotate:
                self.annotate = F(field_name)
            self.filter_field = self.filter_field or field_name
        if self.view.model and not self.model_field:
            self.model_field = self.get_model_field_from_model(self.name)
        if (
            not self.annotate
            and self.model_field
            and (self.model_field.many_to_many or self.model_field.one_to_many)
        ):
            self.annotate = Concat(
                Count(self.model_field.name),
                Value(" - "),
                Value(str(self.model_field.related_model._meta.verbose_name_plural)),
                output_field=CharField(),
            )
            self.filter_field = self.filter_field or self.model_field.name
            if self.auto_created:
                self.detail_visible = False
        if self.model_field:
            self.editable = self.model_field.editable
            if self.model_field.is_relation:
                self.list_visible = (
                    False if self.list_visible_arg is None else self.list_visible_arg
                )
            if self.model_field.auto_created:
                self.detail_visible = False
            self.title = self.title or getattr(
                self.model_field, "verbose_name", self.model_field.name
            )
        if not self.field and self.model_field and self.annotate:
            # suffix field name, so it doesn't clash with model field
            self.field = f"{self.name}{ANNOTATE_KEY}"
        if not self.field:
            self.field = self.name
        if not self.title:
            self.title = self.name
        if self.model_field and not self.python_formatter and not self.view_method:
            if isinstance(self.model_field, DateTimeField):
                self.python_formatter = datetime_formatter
            if isinstance(self.model_field, BooleanField):
                self.python_formatter = boolean_formatter
        self.filter_field = self.filter_field or self.field
        self.init_filter_for_field(configuration)
        self.initialized = True

    def serialize_tabulator(self):
        data = {
            "field": self.field,
            "title": self.title,
            "visible": self.list_visible,
            "formatter": self.formatter,
            "editor": self.tabulator_editor,
        }
        if self.tabulator_options:
            data.update(self.tabulator_options.to_json())
        return data

    def serialize_xlsx(self):
        data = {
            "title": self.title,
            "field": self.field,
            "formatter": self.formatter,
        }
        if self.xlsx_options:
            data.update(self.xlsx_options.to_json())
        return data

    def to_json(self):
        return {
            "title": self.title,
            "field": self.field,
        }

    def get_field_annotates(self, values):
        field_annotates = {}
        supporting_annotates = {}
        if self.annotate:
            field_annotates[self.field] = self.annotate
        if self.annotate_function:
            function_result = self.annotate_function(self, values)
            if function_result:
                field_annotates[self.field] = function_result
            else:
                field_annotates[self.field] = Value(None, output_field=CharField())
        if self.supporting_annotates:
            for key, value in self.supporting_annotates.items():
                # when FilteredRelation is reused more than once, condition inside filter is wrong
                # e.g. instead of
                # delivery_service = FilteredRelation("delivery__service__translations",condition=Q(delivery__service__translations__language_code='sk'))
                # there was
                # delivery_service = FilteredRelation("delivery__service__translations",condition=Q(delivery_service__language_code='sk'))
                # causing error: FieldError: Cannot resolve keyword 'delivery_service' into field.
                if isinstance(value, FilteredRelation):
                    supporting_annotates[key] = value.clone()
                else:
                    supporting_annotates[key] = value
        return {**supporting_annotates, **field_annotates}
