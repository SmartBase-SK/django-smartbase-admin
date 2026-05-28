from django.apps import apps
from django.db import models
from django.db.models import F
from django.forms import BaseInlineFormSet

from django_smartbase_admin.services.thread_local import SBAdminThreadLocalService
from django_smartbase_admin.services.views import SBAdminViewService
from django_smartbase_admin.utils import is_modal


class FakeQueryset(models.QuerySet):
    filter_fake_inline_identifier_by_parent_instance = None

    def __init__(self, model=None, query=None, using=None, hints=None):
        super().__init__(model, query, using, hints)

    def filter(self, *args, **kwargs):
        parent_instance = kwargs.get(SBAdminFakeInlineMixin.fk_name, None)
        if (
            parent_instance
            and isinstance(parent_instance, models.Model)
            and self.filter_fake_inline_identifier_by_parent_instance
        ):
            kwargs.pop(SBAdminFakeInlineMixin.fk_name)
            qs = super().filter(*args, **kwargs)
            qs = self.filter_fake_inline_identifier_by_parent_instance(
                qs, parent_instance
            )
        else:
            qs = super().filter(*args, **kwargs)
        return qs


class SBAdminFakeInlineFormset(BaseInlineFormSet):
    original_model = None
    inline_instance = None

    @classmethod
    def get_default_prefix(cls):
        prefix = super().get_default_prefix()
        modal_prefix = (
            "modal_" if is_modal(SBAdminThreadLocalService.get_request()) else ""
        )
        return f"{modal_prefix}{prefix}"

    def save_new(self, form, commit=True):
        return self.inline_instance.save_new_fake_inline_instance(
            form, self.inline_instance.parent_instance, commit
        )


class SBAdminFakeInlineMixin:
    fk_name = "inline_fake_relationship"
    model_name = "FakeRelationship"
    formset = SBAdminFakeInlineFormset
    original_model = None
    path_to_parent_instance_id = None  # path to parent instance id in fake inline model

    def __init__(self, parent_model, admin_site):
        super().__init__(parent_model, admin_site)
        if self.original_model:
            return
        # Include the inline class name in the dynamic proxy name so
        # two fake inlines on the same (parent, child) pair don't bind
        # to the same proxy and silently overwrite each other's config.
        model_name = (
            f"{self.model._meta.object_name}"
            f"{self.model_name}"
            f"{self.__class__.__name__}"
            f"{self.parent_model._meta.object_name}"
        )
        try:
            fake_model_class = apps.get_model(self.model._meta.app_label, model_name)
        except LookupError:
            fake_model_class = type(
                model_name,
                (self.model,),
                {
                    "__module__": self.__module__,
                    "Meta": type(
                        "Meta",
                        (),
                        {
                            "proxy": True,
                            "verbose_name": self.model._meta.verbose_name,
                            "verbose_name_plural": self.model._meta.verbose_name_plural,
                        },
                    ),
                },
            )
            fake_model_class.original_model = self.model
            fake_model_class._meta.pk.name = self.model._meta.pk.name
        self.original_model = self.model
        self.model = fake_model_class

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        formset.queryset = self.get_queryset(request)
        formset.original_model = self.original_model
        formset.inline_instance = self
        return formset

    def filter_fake_inline_identifier_by_parent_instance(
        self, inline_queryset, parent_instance
    ):
        # filter queryset by parent istance, in queryset there is annotated 'identifier' by get_fake_inline_identifier_annotate
        # example usage:
        # qs = inline_queryset.filter(path_to_parent_instance__id: parent_instance.pk)
        # return qs
        if not self.path_to_parent_instance_id:
            raise NotImplementedError
        qs = inline_queryset.filter(
            **{self.path_to_parent_instance_id: parent_instance.pk}
        )
        return qs

    def filter_fake_inline_identifier_by_parent_pks(self, inline_queryset, parent_pks):
        """Batch filter — restrict ``inline_queryset`` to rows belonging to any
        pk in ``parent_pks``. Used by ``get_data_for_parents`` (read-only batch
        API for related rows; e.g. MCP ``list_rows`` inline hydration).

        Default narrows by ``path_to_parent_instance_id`` — the documented
        join authority. Override **alongside**
        ``filter_fake_inline_identifier_by_parent_instance`` when the custom
        filter can't be expressed as a simple ``path IN (...)`` (extra ``Q``,
        soft-delete masks, traversal through a different join). A one-sided
        override is flagged by ``sbadmin.W004`` and inlines that hit it at
        runtime are skipped by the batch reader.
        """
        if not self.path_to_parent_instance_id:
            raise NotImplementedError
        return inline_queryset.filter(
            **{f"{self.path_to_parent_instance_id}__in": list(parent_pks)}
        )

    def save_new_fake_inline_instance(self, form, parent_instance, commit=True):
        # save new instance of fake inline model
        if not self.path_to_parent_instance_id:
            raise NotImplementedError
        fake_inline_object = form.save(commit=False)
        if parent_instance.pk:
            setattr(
                fake_inline_object, self.path_to_parent_instance_id, parent_instance.pk
            )
            fake_inline_object.save()
        return fake_inline_object

    def get_fake_inline_identifier_annotate(self):
        # this field is used as related 'id' of the inline and can later be used as reference for filtering, so the annotated value
        # should be somehow connected to the parent_instance by which we will filter fake inline model instances
        # result of this method is used in fake_inline_queryset.annotate(SBAdminFakeInlineMixin.fk_name='result')
        # example usage:
        # return F('some_model__relationship_to_parent')
        return F("pk")

    def get_queryset(self, request):
        model = self.original_model
        fake_queryset_class = type(
            "FakeQuerysetClass",
            (FakeQueryset, model._default_manager._queryset_class),
            {},
        )
        fake_queryset_class.filter_fake_inline_identifier_by_parent_instance = (
            self.filter_fake_inline_identifier_by_parent_instance
        )
        manager_class = fake_queryset_class.as_manager()
        manager_class.model = model._default_manager.model
        manager_class._db = model._default_manager._db
        manager_class._hints = model._default_manager._hints
        qs = manager_class.get_queryset()
        ordering = self.get_ordering(request)
        if ordering:
            qs = qs.order_by(*ordering)
        if not self.has_view_or_change_permission(request):
            qs = qs.none()
        qs = qs.annotate(**{self.fk_name: self.get_fake_inline_identifier_annotate()})
        return qs

    def has_permission(self, request, obj=None, permission=None):
        return SBAdminViewService.has_permission(
            request, self, self.original_model, obj, permission
        )


class FakeInlineFilterOverrideMismatchError(NotImplementedError):
    """Batch read can't safely run on a fake inline whose per-parent and batch
    filter hooks are out of sync. Raised by ``get_data_for_parents``; callers
    that do bulk hydration (e.g. MCP ``attach_inlines``) catch it and skip."""


def _is_fake_inline_method_overridden(cls, method_name) -> bool:
    return getattr(cls, method_name) is not getattr(SBAdminFakeInlineMixin, method_name)


def is_fake_inline_batch_safe(cls) -> bool:
    """Whether ``cls``' fake-inline filter hooks are consistent enough for batch read.

    Returns ``False`` only when **exactly one** of
    ``filter_fake_inline_identifier_by_parent_instance`` and
    ``filter_fake_inline_identifier_by_parent_pks`` is overridden — in that
    case the change form and the batch reader would diverge silently.
    Non-fake inlines are always safe.
    """
    if not issubclass(cls, SBAdminFakeInlineMixin):
        return True
    per_parent = _is_fake_inline_method_overridden(
        cls, "filter_fake_inline_identifier_by_parent_instance"
    )
    batch = _is_fake_inline_method_overridden(
        cls, "filter_fake_inline_identifier_by_parent_pks"
    )
    return per_parent == batch
