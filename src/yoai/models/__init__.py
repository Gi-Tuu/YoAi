"""YoAi 真实模型网关适配器包。

定位：把环境变量 / Core .env 里已配好的真实模型网关接成 L2 peer。
所有 key 只在内存使用，不回显、不写盘、不进结果。
"""

from yoai.models.core_anthropic_provider import (
    CoreAnthropicModelProvider,
    core_anthropic_available,
)
from yoai.models.deepseek_adapter import DeepSeekAnthropicAdapter
from yoai.models.gateway_provider import GatewayModelProvider
from yoai.models.expert_provider import ExpertModelProvider
from yoai.models.http_base import (
    ModelHTTPError,
    ModelTransportError,
    friendly_http_error,
    read_env_file,
)
from yoai.models.suanli_adapter import SuanliAdapter

__all__ = [
    "DeepSeekAnthropicAdapter", "SuanliAdapter", "GatewayModelProvider", "ExpertModelProvider",
    "CoreAnthropicModelProvider", "core_anthropic_available",
    "ModelHTTPError", "ModelTransportError", "friendly_http_error", "read_env_file",
]
