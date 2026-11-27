"""多个实例共享同一个 JSON 文件时的同步（S5-0，2026-11-27）。

问题：每个会话的 YoAiAgent 各自 new 一个 PersonalContext / GoalManager / TemporalMemory，
都指向同一个共享文件，但只在构造时读一次。A 会话写入后，B 会话还拿着旧数据，
B 再写就把 A 的内容覆盖掉（已复现："记住我住在杭州"被定时任务的一次写入抹掉）。

做法（不改各类的业务逻辑）：
- 同一进程内，同一个文件共用一把 ``RLock`` 和一个"版本号"，每次保存后版本号 +1；
- 每次读写前比较（版本号, 文件 mtime/大小）：变了就重新加载；
- 写操作在锁内完成"重新加载 → 修改 → 保存"，所以不会再丢别人的写入。
mtime/大小 用来发现**其他进程**（例如命令行工具）改过文件。
"""

from __future__ import annotations

import functools
import os
import threading
from pathlib import Path
from typing import Any, Callable, TypeVar

_registry_lock = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_generations: dict[str, int] = {}

F = TypeVar("F", bound=Callable[..., Any])


def _key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def lock_for(path: str | Path) -> threading.RLock:
    key = _key(path)
    with _registry_lock:
        lock = _locks.get(key)
        if lock is None:
            lock = _locks[key] = threading.RLock()
        return lock


def generation(path: str | Path) -> int:
    with _registry_lock:
        return _generations.get(_key(path), 0)


def bump(path: str | Path) -> None:
    key = _key(path)
    with _registry_lock:
        _generations[key] = _generations.get(key, 0) + 1


def file_signature(path: str | Path) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


class SharedJsonFile:
    """混入类。子类需要：``self.path``、``_load()``（文件不存在时什么都不做）、
    ``_reset_state()``（把内存数据清成空）。构造时调用 ``_init_shared()`` 代替直接 ``_load()``；
    ``_save()`` 末尾调用 ``_mark_saved()``；所有读写文件数据的公开方法加 ``@synced``。"""

    path: Path

    def _init_shared(self) -> None:
        self._sync_lock = lock_for(self.path)
        with self._sync_lock:
            self._reset_state()
            self._load()
            self._seen = (generation(self.path), file_signature(self.path))

    def _reset_state(self) -> None:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def _load(self) -> None:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def _fresh(self) -> None:
        current = (generation(self.path), file_signature(self.path))
        if current != self._seen:
            self._reset_state()
            self._load()
            self._seen = (generation(self.path), file_signature(self.path))

    def _mark_saved(self) -> None:
        bump(self.path)
        self._seen = (generation(self.path), file_signature(self.path))


def synced(fn: F) -> F:
    """方法装饰器：在文件锁内先同步最新数据，再执行原方法（可重入）。"""

    @functools.wraps(fn)
    def wrapper(self: SharedJsonFile, *args: Any, **kwargs: Any) -> Any:
        with self._sync_lock:
            self._fresh()
            return fn(self, *args, **kwargs)

    return wrapper  # type: ignore[return-value]
