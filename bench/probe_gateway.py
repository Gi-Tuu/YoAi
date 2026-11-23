"""通用模型网关探测：填 key 后一次测完能否接入 YoAi。

用法：
  1. 在项目根目录建 .env.gateway（已被 .gitignore 忽略），填三行：
       GATEWAY_BASE_URL=https://www.novapis.com/v1
       GATEWAY_API_KEY=<你的key>
       GATEWAY_MODEL=<模型ID>
  2. python bench/probe_gateway.py

检查项（按 YoAi 生死线排序）：
  ① 端点可达
  ② 模型 ID 是否正确（/models 拉真实列表比对）
  ③ tool_calls 是否支持（YoAi 记忆写入靠这个，不支持=不能接）
  ④ 余额信息（若网关暴露）

安全：key 只从本地文件读入内存，不回显、不写盘、不进日志。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yoai.models.http_base import (  # noqa: E402
    ModelHTTPError, ModelTransportError, post_json, read_env_file,
)

GATEWAY_ENV = ROOT / ".env.gateway"


def post(base: str, key: str, path: str, payload: dict, timeout: float = 30.0) -> dict:
    return post_json(base + path, payload, {"Authorization": "Bearer " + key}, timeout)


def mask(key: str) -> str:
    return key[:4] + "…" + key[-4:] if len(key) > 8 else "***"


def main() -> None:
    if not GATEWAY_ENV.exists():
        print(f"未找到 {GATEWAY_ENV.name}，请先建文件填三行（见本脚本顶部说明）")
        return
    env = read_env_file(GATEWAY_ENV)
    base = env.get("GATEWAY_BASE_URL", "").rstrip("/")
    key = env.get("GATEWAY_API_KEY", "")
    model = env.get("GATEWAY_MODEL", "")
    if not (base and key and model):
        print("缺 GATEWAY_BASE_URL / GATEWAY_API_KEY / GATEWAY_MODEL 任一项")
        return
    print(f"端点: {base}")
    print(f"模型: {model}  key: {mask(key)}", flush=True)

    # ① 端点可达 + ③ tool_calls（合并成一次带 tools 的对话请求）
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say ok"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "remember_event",
                "description": "记住一件事",
                "parameters": {
                    "type": "object",
                    "properties": {"what": {"type": "string"}},
                    "required": ["what"],
                },
            },
        }],
        "tool_choice": "auto",
        "max_tokens": 128,
    }
    print("\n[1/3] 端点 + tool_calls 支持…", flush=True)
    t0 = time.monotonic()
    try:
        data = post(base, key, "/chat/completions", payload)
        elapsed = time.monotonic() - t0
        print(f"  ✅ HTTP 200（{elapsed:.1f}s）")
        choices = data.get("choices", [])
        msg = choices[0].get("message", {}) if choices else {}
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            fn = tool_calls[0].get("function", {})
            print(f"  ✅ tool_calls 支持：{fn.get('name')} {str(fn.get('arguments'))[:60]}")
            print("  → YoAi 记忆写入生死线：通过")
        else:
            content = msg.get("content") or msg.get("reasoning_content") or ""
            print(f"  ⚠️ 本次未返回 tool_calls（content={str(content)[:60]!r}）")
            print("  → 可能不支持函数调用，也可能模型这次选择直接回答；建议再测一次")
    except ModelHTTPError as exc:
        print(f"  ❌ HTTP {exc.status}: {exc.message}")
        if exc.status in (401, 403):
            print("  → key 错误或无权限")
        elif exc.status == 404:
            print("  → 端点路径或模型 ID 错（检查是否带 /v1、模型 ID 是否用 API 返回的值）")
        elif exc.status == 429:
            print("  → 限流")
        return
    except ModelTransportError as exc:
        print(f"  ❌ 连接失败: {exc}")
        return

    # ② 模型 ID 核对（注意：base 已含 /v1，models 路径要用 /models 而非 /v1/models）
    print("\n[2/3] 用 /models 核对模型 ID…", flush=True)
    models_path = "/models" if base.endswith("/v1") else "/v1/models"
    try:
        m = post(base, key, models_path, {}, timeout=15.0)
        ids = [x.get("id", "") for x in m.get("data", [])]
        print(f"  网关可用模型 {len(ids)} 个")
        if model in ids:
            print(f"  ✅ 配置的模型 ID 有效")
        else:
            print(f"  ⚠️ 配置的 {model} 不在列表中")
            print(f"  前 10 个: {ids[:10]}")
    except ModelHTTPError as exc:
        print(f"  ⚠️ /models 返回 HTTP {exc.status}: {exc.message[:80]}")
        print("  → 部分网关不提供此端点；模型 ID 请从控制台复制（第1步的对话测试才是权威）")
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠️ /models 不可用（{type(exc).__name__}），不影响上一步结论")

    # ③ 余额（若网关暴露常见路径）
    print("\n[3/3] 尝试读取余额（非标准，失败正常）…", flush=True)
    for path in ("/dashboard/api/user/self", "/api/user/self", "/v1/usage"):
        try:
            r = post(base, key, path, {}, timeout=10.0)
            if isinstance(r, dict):
                info = {k: v for k, v in r.items()
                        if any(t in k.lower() for t in ("quota", "balance", "credit", "used"))}
                if info:
                    print(f"  {path}: {json.dumps(info, ensure_ascii=False)[:200]}")
                    break
        except Exception:  # noqa: BLE001
            pass
    else:
        print("  未暴露标准余额接口 → 请登录控制台看实际到账")
    print("\n完成。若 tool_calls 通过且模型有效，改 .env 三行即可接入（见候选清单文档）。")


if __name__ == "__main__":
    main()
