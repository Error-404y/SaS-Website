"""Discord account notification payload tests. No external HTTP requests are made."""
import json
import unittest
from unittest.mock import MagicMock, patch

import server


class ImmediateThread:
    def __init__(self, *, target, name, daemon, args=(), kwargs=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.name = name
        self.daemon = daemon

    def start(self):
        self.target(*self.args, **self.kwargs)


class DiscordAccountNotificationTests(unittest.TestCase):
    def test_registration_payload_has_no_secrets_or_mentions(self):
        response = MagicMock()
        response.status = 204
        response.__enter__.return_value = response
        url = "https://discord.com/api/webhooks/123456789/FakeWebhookTokenForTests"
        with patch.object(server, "REGISTRATION_WEBHOOK", url), \
             patch.object(server.threading, "Thread", ImmediateThread), \
             patch.object(server.urllib.request, "urlopen", return_value=response) as deliver:
            server.discord_account_notice("registration", "MEMBER", "@everyone", "test@example.com", "Player Test")
        deliver.assert_called_once()
        request = deliver.call_args.args[0]
        data = json.loads(request.data.decode())
        self.assertEqual(request.full_url, url)
        self.assertEqual(data["allowed_mentions"], {"parse": []})
        self.assertEqual(data["embeds"][0]["title"], "New member registration")
        fields = {item["name"]: item["value"] for item in data["embeds"][0]["fields"]}
        self.assertEqual(fields["Username"], "@everyone")
        self.assertEqual(fields["Role"], "MEMBER")
        self.assertEqual(fields["Email"], "test@example.com")
        self.assertEqual(fields["In-game name"], "Player Test")
        self.assertNotIn("password", json.dumps(data).lower())
        self.assertNotIn("FakeWebhookToken", json.dumps(data))

    def test_successful_login_payload_labels_admin_and_member(self):
        url = "https://discord.com/api/webhooks/123456789/AnotherFakeTestToken"
        response = MagicMock()
        response.status = 204
        response.__enter__.return_value = response
        with patch.object(server, "LOGIN_WEBHOOK", url), \
             patch.object(server.threading, "Thread", ImmediateThread), \
             patch.object(server.urllib.request, "urlopen", return_value=response) as deliver:
            server.discord_account_notice("login", "ADMIN", "admin")
            server.discord_account_notice("login", "MEMBER", "Tester", "user@example.com")
        self.assertEqual(deliver.call_count, 2)
        admin = json.loads(deliver.call_args_list[0].args[0].data)
        member = json.loads(deliver.call_args_list[1].args[0].data)
        self.assertEqual(admin["embeds"][0]["title"], "Website login")
        self.assertEqual(admin["embeds"][0]["fields"][0]["value"], "ADMIN")
        self.assertEqual(member["embeds"][0]["fields"][0]["value"], "MEMBER")
        self.assertEqual(member["embeds"][0]["fields"][2]["value"], "user@example.com")
        self.assertNotIn("Email", [item["name"] for item in admin["embeds"][0]["fields"]])
        for payload in (admin, member):
            fields = {item["name"]: item["value"] for item in payload["embeds"][0]["fields"]}
            self.assertRegex(fields["Login (UTC)"], r"^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2} UTC$")

    def test_invalid_webhook_is_never_called(self):
        with patch.object(server, "LOGIN_WEBHOOK", "http://example.org/evil"), \
             patch.object(server.urllib.request, "urlopen") as deliver:
            server.discord_account_notice("login", "ADMIN", "admin")
        deliver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
