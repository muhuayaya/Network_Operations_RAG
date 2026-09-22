"""适配器和传输层共享的 provider 传输错误类别。"""

from __future__ import annotations


class RateLimitError(RuntimeError):
    """传输层报告可重试的 provider 频率限制。"""


class ProviderTimeoutError(TimeoutError):
    """传输超时，但不暴露请求或凭据内容。"""


class ProviderUnavailableError(RuntimeError):
    """传输层或 provider 不可用。"""


__all__ = ["ProviderTimeoutError", "ProviderUnavailableError", "RateLimitError"]
