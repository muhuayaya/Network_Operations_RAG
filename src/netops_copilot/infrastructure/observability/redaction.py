"""秘密解析和安全日志渲染。"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|password|secret)\s*([=:])(\s*)([^\s,;]+)"
)


class MissingSecretError(ValueError):
    """必需环境变量缺失时抛出，但不包含秘密值。"""

    def __init__(self, environment_variable: str) -> None:
        self.environment_variable = environment_variable
        super().__init__(f"missing required environment variable: {environment_variable}")


def resolve_environment_secret(
    environment_variable: str, environment: Mapping[str, str] | None = None
) -> str:
    """按引用读取非空秘密，但不在错误中显示其值。"""
    source = environment if environment is not None else os.environ
    value = source.get(environment_variable)
    if not value:
        raise MissingSecretError(environment_variable)
    return value


def redact_log_message(message: str, known_secrets: tuple[str, ...] = ()) -> str:
    """从日志消息中移除显式秘密和常见敏感赋值。"""
    redacted = message
    for secret in known_secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1\2\3[REDACTED]", redacted)
