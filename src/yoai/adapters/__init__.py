"""YoAi 外部智能体适配器包。"""

from yoai.adapters.base import AdapterResult, PeerAdapter
from yoai.adapters.cli_adapter import CliAgentAdapter
from yoai.adapters.launch_adapter import LaunchOnlyAdapter
from yoai.adapters.external_peer import ExternalPeer
from yoai.adapters.zen_adapter import ZenAdapter
from yoai.adapters.registry import build_registry, registry_report

__all__ = [
    "PeerAdapter", "AdapterResult", "CliAgentAdapter", "LaunchOnlyAdapter",
    "ExternalPeer", "ZenAdapter", "build_registry", "registry_report",
]
