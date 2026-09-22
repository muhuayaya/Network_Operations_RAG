"""环境变量秘密和日志脱敏测试。"""

from __future__ import annotations

import unittest

from netops_copilot.infrastructure.observability.redaction import (
    MissingSecretError,
    redact_log_message,
    resolve_environment_secret,
)


class SecretHandlingTests(unittest.TestCase):
    """秘密不会进入 Profile 文件、日志或缺失秘密错误。"""

    def test_environment_reference_resolves_without_storing_a_secret(self) -> None:
        self.assertEqual(
            resolve_environment_secret("DASHSCOPE_API_KEY", {"DASHSCOPE_API_KEY": "secret"}),
            "secret",
        )

    def test_missing_secret_reports_only_its_environment_variable_name(self) -> None:
        with self.assertRaises(MissingSecretError) as caught:
            resolve_environment_secret("DASHSCOPE_API_KEY", {})

        self.assertEqual(str(caught.exception), "missing required environment variable: DASHSCOPE_API_KEY")
        self.assertNotIn("secret-value", str(caught.exception))

    def test_log_redaction_hides_known_values_and_assignments(self) -> None:
        message = "api_key=secret-value token: another-secret completed"

        self.assertEqual(
            redact_log_message(message, ("secret-value", "another-secret")),
            "api_key=[REDACTED] token: [REDACTED] completed",
        )
