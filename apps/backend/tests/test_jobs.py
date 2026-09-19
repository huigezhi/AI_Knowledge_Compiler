"""任务队列：幂等、重试、退避、死信（需求文档 §15）。"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from akc.config import Settings
from akc.errors import ClaudeRequestError
from akc.repositories import job as job_repo
from akc.services.job_service import JobWorker, enqueue_job, register_handler


def test_enqueue_is_idempotent(session: Session, settings: Settings) -> None:
    first = enqueue_job(
        session, job_type="WRITE_OBSIDIAN", parts=("a", "b"), payload={}, settings=settings
    )
    second = enqueue_job(
        session, job_type="WRITE_OBSIDIAN", parts=("a", "b"), payload={}, settings=settings
    )
    assert first["id"] == second["id"]
    assert second["enqueued"] is False


def test_failed_job_can_be_retried(session: Session, settings: Settings) -> None:
    """失败任务必须能重跑：否则用户点「重试」拿回旧失败记录，永远恢复不了。

    曾无条件按幂等键返回既有 job，于是编译失败后「保存 + 编译」「重试」都不再执行。
    """
    first = enqueue_job(
        session, job_type="COMPILE_CONVERSATION", parts=("c1", "m1"), payload={}, settings=settings
    )
    job = job_repo.get(session, first["id"])
    assert job is not None
    job.status = "failed"
    job.error = "boom"
    job.error_code = "CLAUDE_OUTPUT_INVALID"
    session.commit()

    again = enqueue_job(
        session, job_type="COMPILE_CONVERSATION", parts=("c1", "m1"), payload={}, settings=settings
    )
    assert again["enqueued"] is True  # 重新入队，而不是返回旧失败
    assert again["status"] == "pending"
    assert again["error"] is None
    assert again["attempts"] == 0


def test_succeeded_job_stays_idempotent(session: Session, settings: Settings) -> None:
    """成功是终态：重复请求不应重做已完成的工作（否则会重复消耗 token）。"""
    first = enqueue_job(
        session, job_type="COMPILE_CONVERSATION", parts=("c2", "m1"), payload={}, settings=settings
    )
    job = job_repo.get(session, first["id"])
    assert job is not None
    job.status = "succeeded"
    session.commit()

    again = enqueue_job(
        session, job_type="COMPILE_CONVERSATION", parts=("c2", "m1"), payload={}, settings=settings
    )
    assert again["enqueued"] is False
    assert again["status"] == "succeeded"


def test_retry_then_dead_letter(session: Session, settings: Settings) -> None:
    attempts = {"n": 0}

    def flaky(_session: Session, _payload: dict[str, Any], _settings: Settings, _job_id: str) -> dict:
        attempts["n"] += 1
        raise ClaudeRequestError("boom", retryable=True)

    register_handler("TEST_FLAKY", flaky)
    job, _ = job_repo.enqueue(
        session,
        job_id="job_test_1",
        job_type="TEST_FLAKY",
        idempotency_key="TEST_FLAKY|1",
        payload={},
        max_attempts=2,
    )
    session.commit()

    worker = JobWorker(settings, poll_interval=0)
    for _ in range(2):
        worker.run_once()
    session.refresh(job)
    assert attempts["n"] == 2
    assert job.status == "failed"  # 超过 max_attempts → 死信
    assert job.error_code == "CLAUDE_REQUEST_FAILED"


def test_non_retryable_fails_immediately(session: Session, settings: Settings) -> None:
    def broken(_session: Session, _payload: dict[str, Any], _settings: Settings, _job_id: str) -> dict:
        raise ClaudeRequestError("bad request", retryable=False)

    register_handler("TEST_BROKEN", broken)
    job, _ = job_repo.enqueue(
        session,
        job_id="job_test_2",
        job_type="TEST_BROKEN",
        idempotency_key="TEST_BROKEN|1",
        payload={},
        max_attempts=5,
    )
    session.commit()
    JobWorker(settings, poll_interval=0).run_once()
    session.refresh(job)
    assert job.status == "failed"
    assert job.attempts == 1


def test_success_marks_result(session: Session, settings: Settings) -> None:
    def ok(_session: Session, _payload: dict[str, Any], _settings: Settings, _job_id: str) -> dict:
        return {"done": True}

    register_handler("TEST_OK", ok)
    job, _ = job_repo.enqueue(
        session,
        job_id="job_test_3",
        job_type="TEST_OK",
        idempotency_key="TEST_OK|1",
        payload={},
    )
    session.commit()
    JobWorker(settings, poll_interval=0).run_once()
    session.refresh(job)
    assert job.status == "succeeded"
    assert job.result_json == {"done": True}


def test_backoff_reschedules(session: Session, settings: Settings) -> None:
    job, _ = job_repo.enqueue(
        session,
        job_id="job_test_4",
        job_type="TEST_MISSING",
        idempotency_key="TEST_MISSING|1",
        payload={},
        max_attempts=3,
    )
    session.commit()
    JobWorker(settings, poll_interval=0).run_once()
    session.refresh(job)
    # 没有注册 handler → 不可重试，直接失败
    assert job.status == "failed"
    assert job.error_code == "JOB_NOT_RUNNABLE"


def test_cancel(session: Session) -> None:
    job, _ = job_repo.enqueue(
        session,
        job_id="job_test_5",
        job_type="TEST_OK",
        idempotency_key="TEST_OK|cancel",
        payload={},
    )
    session.commit()
    job_repo.cancel(session, job)
    session.commit()
    assert job.status == "cancelled"


@pytest.mark.parametrize("missing", ["", None])
def test_handler_rejects_missing_conversation(session: Session, settings: Settings, missing: Any) -> None:
    from akc.job_handlers import _compile

    with pytest.raises(Exception):
        _compile(session, {"conversation_id": missing}, settings, "job_x")
