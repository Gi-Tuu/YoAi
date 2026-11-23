"""M0 网关并发上限实测（评测提速立项）。

用真实算里网关的小 payload 测不同并发数下的成功率/延迟/限流信号。
key 只在内存使用，不回显、不写盘。

用法：python bench/probe_concurrency.py
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(r"E:\Competition\YAI Agent Core") / "src"))

from yoai.models.http_base import (  # noqa: E402
    ModelHTTPError, ModelTransportError, post_json, read_env_file,
)

CORE_ENV = Path(r"E:\Competition\YAI Agent Core") / ".env"
LEVELS = [1, 2, 4, 8, 16, 32]
# 每档请求数必须远大于最大并发数，否则高档位 worker 空转、测不出上限。
# 旧版 PER_LEVEL=8 导致"16路"只提交8个任务(一半worker空闲)，
# 得出"8路甜蜜点"是测试设计假象，非网关真实上限。
PER_LEVEL = 128
PAYLOAD = {
    "model": "deepseek/deepseek-v4.1-flash-1017",
    "messages": [{"role": "user", "content": "Reply with one word: ok"}],
    "max_tokens": 16,
    "temperature": 0.1,
}


def one_request(url: str, headers: dict[str, str]) -> tuple[bool, float, str]:
    t0 = time.monotonic()
    try:
        post_json(url, PAYLOAD, headers, 60.0)
        return True, time.monotonic() - t0, "ok"
    except ModelHTTPError as exc:
        return False, time.monotonic() - t0, f"http_{exc.status}"
    except ModelTransportError as exc:
        return False, time.monotonic() - t0, "transport"
    except Exception as exc:  # noqa: BLE001
        return False, time.monotonic() - t0, type(exc).__name__


def run_level(level: int, url: str, headers: dict[str, str]) -> dict:
    t0 = time.monotonic()
    results: list[tuple[bool, float, str]] = []
    with ThreadPoolExecutor(max_workers=level) as pool:
        futures = [pool.submit(one_request, url, headers) for _ in range(PER_LEVEL)]
        for f in as_completed(futures):
            results.append(f.result())
    wall = time.monotonic() - t0
    ok = sum(1 for r in results if r[0])
    lat = [r[1] for r in results if r[0]]
    errors = [r[2] for r in results if not r[0]]
    return {
        "level": level, "ok": ok, "total": PER_LEVEL,
        "wall_s": round(wall, 2), "avg_lat_s": round(sum(lat) / len(lat), 2) if lat else None,
        "throughput_rps": round(PER_LEVEL / wall, 2), "errors": errors,
    }


def main() -> None:
    env = read_env_file(CORE_ENV)
    base = env.get("OPENAI_BASE_URL", "").rstrip("/")
    key = env.get("OPENAI_API_KEY", "")
    if not base or not key:
        print("CONFIG_ERROR: 缺少 base_url 或 key")
        return
    url = base + "/chat/completions"
    headers = {"Authorization": "Bearer " + key}

    print(f"M0 并发上限实测 · 每档 {PER_LEVEL} 请求 · 网关 {base}", flush=True)
    print(f"{'并发':>4} {'成功':>8} {'墙钟s':>8} {'均延迟s':>8} {'吞吐rps':>9}  错误", flush=True)
    for level in LEVELS:
        r = run_level(level, url, headers)
        err = ",".join(r["errors"][:4]) if r["errors"] else "-"
        print(f"{level:>4} {r['ok']:>3}/{r['total']:<4} {r['wall_s']:>8} "
              f"{str(r['avg_lat_s']):>8} {r['throughput_rps']:>9}  {err}", flush=True)


if __name__ == "__main__":
    main()
