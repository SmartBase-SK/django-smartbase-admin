"""Tests for ``MessageAttachment`` upload-path / storage resolution.

Locks the documented ``SB_ADMIN_MESSAGING_ATTACHMENT_UPLOAD_TO`` /
``SB_ADMIN_MESSAGING_ATTACHMENT_STORAGE`` settings contract, in particular that
an explicit empty string is a *valid* value meaning "store at the storage /
container root" (distinct from unset, which keeps the default prefix).
"""

from django.core.files.storage import default_storage
from django.test import SimpleTestCase, override_settings

from django_smartbase_admin.messaging.models import (
    DEFAULT_MESSAGE_ATTACHMENT_UPLOAD_TO,
    message_attachment_storage,
    message_attachment_upload_to,
)


class MessageAttachmentUploadToTestCase(SimpleTestCase):
    def test_unset_uses_default_prefix(self):
        # No setting at all -> default prefix.
        self.assertEqual(
            message_attachment_upload_to(None, "file.pdf"),
            DEFAULT_MESSAGE_ATTACHMENT_UPLOAD_TO + "file.pdf",
        )

    @override_settings(SB_ADMIN_MESSAGING_ATTACHMENT_UPLOAD_TO=None)
    def test_explicit_none_uses_default_prefix(self):
        self.assertEqual(
            message_attachment_upload_to(None, "file.pdf"),
            DEFAULT_MESSAGE_ATTACHMENT_UPLOAD_TO + "file.pdf",
        )

    @override_settings(SB_ADMIN_MESSAGING_ATTACHMENT_UPLOAD_TO="")
    def test_empty_string_is_valid_and_means_root(self):
        # The documented behaviour: "" is a valid value -> container root,
        # i.e. the bare filename with no prefix.
        self.assertEqual(message_attachment_upload_to(None, "file.pdf"), "file.pdf")

    @override_settings(SB_ADMIN_MESSAGING_ATTACHMENT_UPLOAD_TO="tenant/attachments/")
    def test_string_prefix(self):
        self.assertEqual(
            message_attachment_upload_to(None, "file.pdf"),
            "tenant/attachments/file.pdf",
        )

    @override_settings(
        SB_ADMIN_MESSAGING_ATTACHMENT_UPLOAD_TO=lambda instance, filename: f"x/{filename}"
    )
    def test_callable_override(self):
        self.assertEqual(message_attachment_upload_to(None, "file.pdf"), "x/file.pdf")


class MessageAttachmentStorageTestCase(SimpleTestCase):
    def test_unset_uses_default_storage(self):
        self.assertIs(message_attachment_storage(), default_storage)

    @override_settings(SB_ADMIN_MESSAGING_ATTACHMENT_STORAGE=None)
    def test_explicit_none_uses_default_storage(self):
        self.assertIs(message_attachment_storage(), default_storage)

    @override_settings(
        STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}}
    )
    @override_settings(SB_ADMIN_MESSAGING_ATTACHMENT_STORAGE="default")
    def test_string_alias_resolves_from_storages(self):
        from django.core.files.storage import storages

        self.assertIs(message_attachment_storage(), storages["default"])

    def test_instance_is_returned_as_is(self):
        from django.core.files.storage import FileSystemStorage

        sentinel = FileSystemStorage(location="/tmp/attachments")
        with override_settings(SB_ADMIN_MESSAGING_ATTACHMENT_STORAGE=sentinel):
            self.assertIs(message_attachment_storage(), sentinel)

    def test_callable_override_is_invoked(self):
        from django.core.files.storage import FileSystemStorage

        sentinel = FileSystemStorage(location="/tmp/attachments")
        with override_settings(SB_ADMIN_MESSAGING_ATTACHMENT_STORAGE=lambda: sentinel):
            self.assertIs(message_attachment_storage(), sentinel)
