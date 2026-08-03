from django import forms
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.forms.utils import ErrorList
from django.test import SimpleTestCase

from django_smartbase_admin.mcp.form_encoding import (
    form_errors_dict,
    formset_errors_dict,
)


class FormErrorEncodingTests(SimpleTestCase):
    def test_plain_error_mapping_is_serialized(self):
        form = forms.Form(data={})
        form._errors = {
            "name": ErrorList([ValidationError("Invalid name.", code="invalid_name")]),
            NON_FIELD_ERRORS: ["Form-wide failure."],
        }

        self.assertEqual(
            form_errors_dict(form),
            {
                "non_field": [{"code": None, "message": "Form-wide failure."}],
                "fields": {
                    "name": [{"code": "invalid_name", "message": "Invalid name."}]
                },
            },
        )

    def test_formset_with_plain_row_errors_is_serialized(self):
        formset_class = forms.formset_factory(forms.Form, extra=1)
        formset = formset_class(
            data={
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "1000",
            }
        )
        form = formset.forms[0]
        form._errors = {
            "value": [ValidationError("Invalid value.", code="invalid_value")]
        }
        formset._errors = [form._errors]
        formset._non_form_errors = [
            ValidationError("Formset failure.", code="invalid_formset")
        ]

        self.assertEqual(
            formset_errors_dict(formset),
            {
                "type": "formset",
                "non_form": [
                    {"code": "invalid_formset", "message": "Formset failure."}
                ],
                "rows": [
                    {
                        "index": 0,
                        "non_field": [],
                        "fields": {
                            "value": [
                                {
                                    "code": "invalid_value",
                                    "message": "Invalid value.",
                                }
                            ]
                        },
                    }
                ],
            },
        )
