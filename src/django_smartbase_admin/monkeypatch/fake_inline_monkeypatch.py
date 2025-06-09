from django.forms import models as forms_models


def monkeypatch_get_foreign_key(fnc):
    def _get_foreign_key(parent_model, model, fk_name=None, can_fail=False):
        try:
            result = fnc(parent_model, model, fk_name, can_fail)
        except ValueError as e:
            from django.db import models
            from django_smartbase_admin.engine.fake_inline import SBAdminFakeInlineMixin

            if SBAdminFakeInlineMixin.model_name not in model._meta.label:
                raise e
            result = models.ForeignKey(
                model.original_model, on_delete=models.DO_NOTHING
            )
            result.set_attributes_from_name(SBAdminFakeInlineMixin.fk_name)

        return result

    return _get_foreign_key


forms_models._get_foreign_key = monkeypatch_get_foreign_key(
    forms_models._get_foreign_key
)
