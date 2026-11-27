"""调度器持久化（对齐 OpenClaw：jobs.json + 每个任务一个运行日志 jsonl，自动裁剪）。

- ``jobs.json``：原子写（临时文件 → fsync → os.replace）；坏 JSON 改名为 ``.corrupt``
  保留现场后从空开始，不崩溃。文件被外部改动（例如命令行工具添加任务）时，
  下一次 ``refresh()`` 会重新加载。
- ``runs/<job_id>.jsonl``：只追加，每行是某次运行的一个状态快照，同一 run_id 以
  **最后一行**为准；文件超过 ``max_bytes`` 时只保留最新 ``keep_lines`` 行
  （默认值与 OpenClaw cron.runLog 相同：2_000_000 字节 / 2000 行）。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from yoai.scheduler.models import (
    RUN_INTERRUPTED,
    RUN_RUNNING,
    Job,
    RunRecord,
    now_utc,
    to_iso,
)

RUNLOG_MAX_BYTES = 2_000_000
RUNLOG_KEEP_LINES = 2000
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".yoai-sched-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


class SchedulerStore:
    def __init__(self, root: str | Path, *, max_bytes: int = RUNLOG_MAX_BYTES,
                 keep_lines: int = RUNLOG_KEEP_LINES) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs_dir = self.root / "runs"
        self.runs_dir.mkdir(exist_ok=True)
        self.jobs_path = self.root / "jobs.json"
        self.max_bytes = max_bytes
        self.keep_lines = keep_lines
        self._jobs: dict[str, Job] = {}
        self._mtime: int | None = None
        # 对话工具可能在工作线程里改任务，与事件循环里的 tick 并发——任务表统一加锁
        self._lock = threading.RLock()
        self._load()

    # ---- jobs ----
    def _stat_mtime(self) -> int | None:
        try:
            return self.jobs_path.stat().st_mtime_ns
        except OSError:
            return None

    def _load(self) -> None:
        with self._lock:
            self._load_locked()

    def _load_locked(self) -> None:
        self._mtime = self._stat_mtime()
        if self._mtime is None:
            self._jobs = {}
            return
        try:
            raw = json.loads(self.jobs_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("jobs.json 顶层不是对象")
            jobs: dict[str, Job] = {}
            for job_id, item in raw.items():
                if isinstance(item, dict):
                    job = Job.from_dict({**item, "id": item.get("id", job_id)})
                    jobs[job.id] = job
            self._jobs = jobs
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            backup = self.jobs_path.with_suffix(self.jobs_path.suffix + ".corrupt")
            try:
                self.jobs_path.replace(backup)
            except OSError:
                pass
            self._jobs = {}
            self._mtime = None

    def refresh(self) -> bool:
        """jobs.json 被外部改过就重新加载；返回是否重载。"""
        with self._lock:
            current = self._stat_mtime()
            if current is not None and current != self._mtime:
                self._load_locked()
                return True
            return False

    def _save(self) -> None:
        payload = {jid: job.to_dict() for jid, job in self._jobs.items()}
        _atomic_write(self.jobs_path,
                      json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        self._mtime = self._stat_mtime()

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def save(self, job: Job) -> Job:
        """新增或覆盖（调用方负责先 validate）。"""
        with self._lock:
            job.touch()
            self._jobs[job.id] = job
            self._save()
            return job

    def delete(self, job_id: str) -> bool:
        with self._lock:
            if self._jobs.pop(job_id, None) is None:
                return False
            self._save()          # 运行日志保留，便于审计与 RSI 取样
            return True

    # ---- runs ----
    def run_file(self, job_id: str) -> Path:
        return self.runs_dir / f"{_SAFE_ID.sub('_', job_id) or '_'}.jsonl"

    def append_run(self, record: RunRecord) -> None:
        path = self.run_file(record.job_id)
        line = json.dumps(record.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._prune(path)

    def _prune(self, path: Path) -> None:
        try:
            if path.stat().st_size <= self.max_bytes:
                return
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        kept = [ln for ln in lines if ln.strip()][-self.keep_lines:]
        _atomic_write(path, "\n".join(kept) + "\n")

    @staticmethod
    def _read_file(path: Path, latest: dict[str, RunRecord]) -> None:
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw: Any = json.loads(line)
                    except json.JSONDecodeError:
                        continue          # 半行（断电时写了一半）直接跳过
                    if isinstance(raw, dict) and raw.get("run_id"):
                        latest[str(raw["run_id"])] = RunRecord.from_dict(raw)
        except OSError:
            return

    def _latest_runs(self, job_id: str = "") -> dict[str, RunRecord]:
        latest: dict[str, RunRecord] = {}
        files = [self.run_file(job_id)] if job_id else sorted(self.runs_dir.glob("*.jsonl"))
        for path in files:
            if path.exists():
                self._read_file(path, latest)
        return latest

    def runs(self, job_id: str = "", limit: int = 20) -> list[RunRecord]:
        items = list(self._latest_runs(job_id).values())
        items.sort(key=lambda r: (r.started_at, r.finished_at or "~"), reverse=True)
        return items[:limit] if limit > 0 else items

    def open_runs(self) -> list[RunRecord]:
        """有 running、但没有终态记录的运行（= 上次进程异常退出时正在跑的）。"""
        return [r for r in self._latest_runs().values() if r.state == RUN_RUNNING]

    def mark_interrupted(self) -> list[RunRecord]:
        marked = []
        for record in self.open_runs():
            record.state = RUN_INTERRUPTED
            record.finished_at = to_iso(now_utc())
            record.summary = record.summary or "上次运行时应用被关闭或异常退出"
            self.append_run(record)
            marked.append(record)
        return marked
