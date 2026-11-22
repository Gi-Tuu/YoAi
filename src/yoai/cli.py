"""YoAi CLI — 最小交互入口。

用法：
    python -m yoai.cli "记住我偏好深色主题"      # 单次任务（离线脚本模型演示）
    python -m yoai.cli --tools                   # 列出已注册工具
    python -m yoai.cli                           # 查看状态（目标/事实条数）

真实上线把 YoAiAgent(model=OpenAICompatProvider()) 注入即可（见 README）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yoai", description="YoAi 个人智能体")
    parser.add_argument("task", nargs="?", help="要执行的任务文本")
    parser.add_argument("--tools", action="store_true", help="列出已注册工具")
    parser.add_argument(
        "--data-dir", dest="data_dir", default=None, help="个人状态数据目录"
    )
    return parser


async def _run_task(agent, task: str) -> None:
    from yai_core import EventType

    print(f"任务：{task}")
    async for event in agent.astream(task):
        if event.type == EventType.STRATEGY_SELECTED:
            print(f"[路由] {event.data['strategy']}")
        elif event.type == EventType.TOOL_CALL:
            print(f"[工具] {event.data['tool']}({event.data['arguments']})")
        elif event.type == EventType.DONE:
            print(f"[完成] {event.data['final_text']}")
    print(f"状态：{agent.context.count()} 条事实 / {agent.goals.count()} 个目标")


def main() -> int:
    args = _build_parser().parse_args()
    from yoai.agent import YoAiAgent

    agent = YoAiAgent(data_dir=args.data_dir)
    if args.tools:
        print("已注册工具：", ", ".join(agent.list_tools()))
        return 0
    if args.task:
        asyncio.run(_run_task(agent, args.task))
        return 0
    # 无参数：展示本地状态
    print(f"YoAi 本地状态：{agent.context.count()} 条个人事实 / "
          f"{agent.goals.count()} 个长期目标")
    print("工具：", ", ".join(agent.list_tools()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
