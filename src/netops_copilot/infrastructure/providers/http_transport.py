"""面向 OpenAI 兼容 provider 的小型安全秘密 HTTP 传输层。

provider 适配器有意依赖注入的可调用对象，使单元测试不需要网络连接。
本模块为演示运行时提供生产调用对象，同时不把 SDK 引入应用层。
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from netops_copilot.infrastructure.providers.errors import (
    ProviderTimeoutError,
    ProviderUnavailableError,
    RateLimitError,
)


@dataclass(frozen=True, slots=True)
class OpenAICompatibleHttpTransport:
    """向 OpenAI 兼容基础 URL 发送 POST JSON 请求。

    错误消息只包含安全的 HTTP 状态/类别；provider 响应体可能包含敏感数据，绝不暴露。
    """

    base_url: str
    user_agent: str = "netops-copilot/0.1"

    def __post_init__(self) -> None:
        normalized = self.base_url.rstrip("/")
        if not normalized.startswith(("http://", "https://")) or "://" not in normalized:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        object.__setattr__(self, "base_url", normalized)

    def __call__(
        self,
        path: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        if not path.startswith("/"):
            raise ValueError("provider request path must start with '/'")
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            **dict(headers),
        }
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=request_headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 429:
                raise RateLimitError("provider rate limit") from error
            if error.code in {408, 504}:
                raise ProviderTimeoutError("provider request timed out") from error
            raise ProviderUnavailableError(f"provider HTTP status {error.code}") from error
        except TimeoutError as error:
            raise ProviderTimeoutError("provider request timed out") from error
        except (URLError, OSError) as error:
            raise ProviderUnavailableError("provider connection unavailable") from error
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderUnavailableError("provider returned invalid JSON") from error
        if not isinstance(decoded, Mapping):
            raise ProviderUnavailableError("provider returned a non-object response")
        return decoded


__all__ = ["OpenAICompatibleHttpTransport"]
