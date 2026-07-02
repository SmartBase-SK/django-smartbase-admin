"""Tests for ``SBAdminMessagingService.create_message`` — programmatic authoring
of messages outside the admin (commands, signals, other services).
"""

import tempfile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from django_smartbase_admin.messaging.config import (
    SBAdminMessagingConfig,
    UsersAudience,
)
from django_smartbase_admin.messaging.models import Message, MessageRecipient
from django_smartbase_admin.messaging.services import SBAdminMessagingService


class CreateMessageTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.u1 = User.objects.create_user(username="u1")
        cls.u2 = User.objects.create_user(username="u2")

    def test_explicit_user_ids_create_unread_recipients(self):
        message = SBAdminMessagingService.create_message(
            title="Hi",
            type="info",
            content="<p>body</p>",
            user_ids=[self.u1.pk, self.u2.pk],
        )
        self.assertIsInstance(message, Message)
        recipients = MessageRecipient.objects.filter(message=message)
        self.assertEqual(
            set(recipients.values_list("user_id", flat=True)),
            {self.u1.pk, self.u2.pk},
        )
        # All recipients start unread / un-notified.
        self.assertEqual(recipients.filter(read_at__isnull=False).count(), 0)
        self.assertEqual(recipients.filter(notified_at__isnull=False).count(), 0)

    def test_targeting_resolved_via_messaging_config(self):
        config = SBAdminMessagingConfig(audiences=[UsersAudience()])
        message = SBAdminMessagingService.create_message(
            title="Targeted",
            type="info",
            targeting={"users": [self.u1.pk]},
            messaging_config=config,
        )
        self.assertEqual(
            list(
                MessageRecipient.objects.filter(message=message).values_list(
                    "user_id", flat=True
                )
            ),
            [self.u1.pk],
        )

    def test_explicit_and_targeting_are_unioned_without_duplicates(self):
        config = SBAdminMessagingConfig(audiences=[UsersAudience()])
        message = SBAdminMessagingService.create_message(
            title="Both",
            type="info",
            targeting={"users": [self.u1.pk]},
            messaging_config=config,
            user_ids=[self.u1.pk, self.u2.pk],  # u1 overlaps targeting
        )
        recipients = MessageRecipient.objects.filter(message=message)
        self.assertEqual(recipients.count(), 2)
        self.assertEqual(
            set(recipients.values_list("user_id", flat=True)),
            {self.u1.pk, self.u2.pk},
        )

    def test_no_recipients_when_nothing_targeted(self):
        message = SBAdminMessagingService.create_message(title="Lonely", type="info")
        self.assertEqual(MessageRecipient.objects.filter(message=message).count(), 0)

    def test_attachments_are_saved(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                message = SBAdminMessagingService.create_message(
                    title="With file",
                    type="info",
                    user_ids=[self.u1.pk],
                    attachments=[ContentFile(b"hello", name="note.txt")],
                )
        attachments = list(message.attachments.all())
        self.assertEqual(len(attachments), 1)
        self.assertTrue(attachments[0].file.name.endswith("note.txt"))
