"""命令行管理定时任务（S4 界面做好之前用来测试）。

用法（在 YoAi 根目录）：
    python -m yoai.scheduler list
    python -m yoai.scheduler add --name 测试 --prompt "列出我的目标" --in 2
    python -m yoai.scheduler add --name 早间回顾 --prompt "..." --daily 09:00
    python -m yoai.scheduler add --name 工作日 --prompt "..." --cron "30 9 * * 1-5"
    python -m yoai.scheduler enable heartbeat
    python -m yoai.scheduler runs [任务ID]
    python -m yoai.scheduler remove <任务ID>

数据目录：默认 YOAI_DATA_DIR，否则项目根的 output/。
**dist 版 YoAi.exe 的数据目录是 dist/output**，测试 exe 时加 --data-dir dist/output。
应用运行中修改也可以：调度器每 30 秒检查一次 jobs.json 是否被外部改过。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from yoai.scheduler.engine import SchedulerEngine
from yoai.scheduler.models import Job, RunResult, SchedulerError, Trigger, from_iso
from yoai.scheduler.store import SchedulerStore
from yoai.scheduler.triggers import describe, local_tz


def default_data_dir() -> Path:
    env = os.environ.get("YOAI_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[3] / "output"


async def _no_run(job, record, prompt):  # 命令行只管理，不执行
    return RunResult(ok=False, summary="命令行不执行任务")


def _engine(data_dir: Path) -> SchedulerEngine:
    return SchedulerEngine(SchedulerStore(data_dir / "scheduler"), _no_run)


def _trigger(args: argparse.Namespace) -> Trigger:
    tz = args.tz or ""
    if args.in_minutes is not None:
        at = datetime.now(local_tz()) + timedelta(minutes=args.in_minutes)
        return Trigger(kind="once", at=at.isoformat(timespec="seconds"), tz=tz)
    if args.at:
        dt = datetime.fromisoformat(args.at)
        if dt.tzinfo is None:                 # 命令行里不带时区 = 本地时间（更符合直觉）
            dt = dt.replace(tzinfo=local_tz())
        return Trigger(kind="once", at=dt.isoformat(), tz=tz)
    if args.every is not None:
        return Trigger(kind="interval", every_s=int(args.every * 60), tz=tz)
    if args.daily:
        return Trigger(kind="daily", time=args.daily, tz=tz)
    if args.weekly:
        days, _, at = args.weekly.partition("@")
        return Trigger(kind="weekly", weekdays=[int(d) for d in days.split(",") if d],
                       time=at, tz=tz)
    if args.cron:
        return Trigger(kind="cron", expr=args.cron, tz=tz)
    raise SchedulerError("请指定一种时间：--in / --at / --every / --daily / --weekly / --cron")


def _print_job(job: Job) -> None:
    nxt = from_iso(job.next_fire_at)
    when = nxt.astimezone(local_tz()).strftime("%m-%d %H:%M") if nxt else "—"
    flag = "开" if job.enabled else "关"
    print(f"{job.id:10} [{flag}] {job.name:12} {describe(job.trigger):18} 下次 {when:12} "
          f"上次 {job.last_state or '—'}" + (f"（{job.disabled_reason}）" if job.disabled_reason else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m yoai.scheduler", description="YoAi 定时任务")
    parser.add_argument("--data-dir", type=Path, default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    add = sub.add_parser("add")
    add.add_argument("--name", required=True)
    add.add_argument("--prompt", required=True)
    add.add_argument("--in", dest="in_minutes", type=float, help="N 分钟后运行一次")
    add.add_argument("--at", help="一次性：2026-11-28 09:00（不带时区=本地）")
    add.add_argument("--every", type=float, help="每 N 分钟（至少 5）")
    add.add_argument("--daily", help="每天 HH:MM")
    add.add_argument("--weekly", help="星期几@HH:MM，0=周一，例如 0,3@20:00")
    add.add_argument("--cron", help='cron 表达式，例如 "30 9 * * 1-5"（需要 croniter）')
    add.add_argument("--tz", default="", help="时区，例如 +08:00 或 Asia/Shanghai；默认本地")
    add.add_argument("--active-hours", default="", help="执行时间窗，例如 08:00-23:00")
    add.add_argument("--allow", default="", help="额外放行的工具，逗号分隔（危险工具始终不放行）")
    add.add_argument("--disabled", action="store_true", help="创建后先不开启")
    for name in ("remove", "enable", "disable"):
        sub.add_parser(name).add_argument("job_id")
    runs = sub.add_parser("runs")
    runs.add_argument("job_id", nargs="?", default="")
    runs.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)

    data_dir = args.data_dir or default_data_dir()
    eng = _engine(data_dir)
    try:
        if args.cmd == "list":
            jobs = eng.store.list_jobs()
            if not jobs:
                print("还没有定时任务。")
            for job in jobs:
                _print_job(job)
        elif args.cmd == "add":
            job = Job(name=args.name, prompt=args.prompt, trigger=_trigger(args),
                      active_hours=args.active_hours, enabled=not args.disabled,
                      allowed_tools=[t.strip() for t in args.allow.split(",") if t.strip()],
                      created_by="cli")
            _print_job(eng.add_job(job))
        elif args.cmd == "remove":
            print("已删除" if eng.remove_job(args.job_id) else "找不到这个任务")
        elif args.cmd in ("enable", "disable"):
            _print_job(eng.set_enabled(args.job_id, args.cmd == "enable"))
        elif args.cmd == "runs":
            for r in eng.store.runs(args.job_id, limit=args.limit):
                quiet = "（安静）" if r.quiet else ""
                denied = f" 被拒工具：{','.join(r.denied_tools)}" if r.denied_tools else ""
                print(f"{r.started_at[:19]} {r.job_name or r.job_id:12} {r.state:11}{quiet} "
                      f"{r.reason:18} {r.summary[:60]}{denied}")
    except SchedulerError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(f"（数据目录：{data_dir}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
