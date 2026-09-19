"""SQLite 任务队列：入队、调度、重试、死信（需求文档 §15）。

设计：
* 幂等键唯一，重复入队不会重复执行；
* 指数退避（默认 2s / 5s / 15s），不可恢复错误不得无限重试；
* 每个 job 都有 ``stage``，前端展示阶段而不是虚假百分比；
* worker 为后台线程，服务关闭时优雅停机。
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

from sqlalchemy.orm import Session

from akc.config import Settings
from akc.db import get_session_factory
from akc.errors import AppError
from akc.logging_setup import get_logger, log_event
from akc.repositories import job as job_repo

# job_type -> handler(session, payload, settings, job_id) -> result dict
Handler = Callable[[Session, dict[str, Any], Settings, str], dict[str, Any]]
_HANDLERS: dict[str, Handler] = {}


def register_handler(job_type: str, handler: Handler) -> None:
    _HANDLERS[job_type] = handler


def idempotency_key(job_type: str, *parts: Any) -> str:
    return "|".join([job_type, *(str(p) for p in parts)])


def new_job_id() -> str:
    return f"job_{uuid.uuid4().hex[:20]}"


def enqueue_job(
    session: Session,
    *,
    job_type: str,
    parts: tuple[Any, ...],
    payload: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """入队并返回 job dict。已存在相同幂等键时返回既有 job。"""
    job, created = job_repo.enqueue(
        session,
        job_id=new_job_id(),
        job_type=job_type,
        idempotency_key=idempotency_key(job_type, *parts),
        payload=payload,
        max_attempts=settings.job_max_attempts,
    )
    session.commit()
    return {**job_repo.to_dict(job), "enqueued": created}


class JobWorker:
    """后台单消费者 worker。MVP 串行执行即可满足本地桌面场景。"""

    def __init__(self, settings: Settings, *, poll_interval: float | None = None) -> None:
        self._settings = settings
        self._poll_interval = poll_interval or settings.job_poll_interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="akc-job-worker", daemon=True
        )
        self._thread.start()
        get_logger().info("job_worker_started")

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        get_logger().info("job_worker_stopped")

    def run_once(self) -> bool:
        """取出并执行一个到期任务。返回是否处理了任务。"""
        factory = get_session_factory()
        session = factory()
        try:
            job = job_repo.claim_next(session)
            if job is None:
                session.rollback()
                return False
            session.commit()
            self._execute(job.id)
            return True
        finally:
            session.close()

    # ------------------------------------------------------------------ 内部
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.run_once()
            except Exception:  # noqa: BLE001 - worker 不能因为单个异常退出
                get_logger().exception("job_worker_iteration_failed")
                processed = False
            # 没有任务时按退避间隔休眠，避免忙等
            self._stop.wait(self._poll_interval if not processed else 0.05)

    def _execute(self, job_id: str) -> None:
        factory = get_session_factory()
        session = factory()
        try:
            job = job_repo.get(session, job_id)
            if job is None:
                return
            handler = _HANDLERS.get(job.job_type)
            if handler is None:
                job_repo.mark_failed(
                    session,
                    job,
                    error=f"no handler registered for job_type={job.job_type}",
                    error_code="JOB_NOT_RUNNABLE",
                    retryable=False,
                    backoff_seconds=self._settings.job_backoff_seconds,
                )
                session.commit()
                return

            try:
                result = handler(session, dict(job.payload_json or {}), self._settings, job.id)
                job_repo.mark_succeeded(session, job, result)
                session.commit()
                log_event("job_succeeded", job_id=job.id, job_type=job.job_type)
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                job = job_repo.get(session, job_id)  # 回滚后重新读取
                if job is None:
                    return
                retryable = bool(getattr(exc, "retryable", True))
                code = getattr(exc, "code", None)
                job_repo.mark_failed(
                    session,
                    job,
                    error=str(exc)[:2000],
                    error_code=getattr(code, "value", str(code)) if code else None,
                    retryable=retryable and not isinstance(exc, (KeyboardInterrupt, SystemExit)),
                    backoff_seconds=self._settings.job_backoff_seconds,
                )
                session.commit()
                log_event(
                    "job_failed",
                    job_id=job.id,
                    job_type=job.job_type,
                    attempts=job.attempts,
                    retryable=retryable,
                )
        finally:
            session.close()


def drain_once(settings: Settings, *, max_iterations: int = 50) -> int:
    """测试与 CLI 用：同步把队列跑空。返回处理任务数。"""
    worker = JobWorker(settings, poll_interval=0)
    processed = 0
    for _ in range(max_iterations):
        try:
            if not worker.run_once():
                break
        except AppError:
            break
        processed += 1
        time.sleep(0)
    return processed
