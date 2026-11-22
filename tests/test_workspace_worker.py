"""Worker behavior around handlers, retries, and lost leases."""

from datetime import timedelta
from threading import Event
from unittest.mock import MagicMock
import uuid

import pytest

from src.workspace.jobs import queue, worker


@pytest.fixture
def claimed(monkeypatch):
    job = queue.ClaimedJob(uuid.uuid4(), uuid.uuid4(), "import", {}, uuid.uuid4(), 1)
    monkeypatch.setattr(queue, "claim_job", lambda *args, **kwargs: job)
    finish = MagicMock(return_value=True)
    monkeypatch.setattr(queue, "finish_job", finish)
    return job, finish


def test_success_calls_handler_and_finishes(claimed):
    job, finish = claimed
    handler = MagicMock()
    database = MagicMock()
    assert worker.Worker(database, {"import": handler}).run_once()
    assert handler.call_args.args[0] == job
    finish.assert_called_once_with(database, job.id, job.lease_token, success=True, retryable=False)


@pytest.mark.parametrize("error,retryable", [(worker.PermanentJobError("private"), False), (RuntimeError("private"), True)])
def test_handler_errors_are_sanitized_and_classified(claimed, error, retryable, caplog):
    job, finish = claimed
    def fail(*_):
        raise error
    database = MagicMock()
    worker.Worker(database, {"import": fail}).run_once()
    finish.assert_called_once_with(database, job.id, job.lease_token, success=False, retryable=retryable)
    assert "private" not in caplog.text


def test_lost_lease_does_not_finish_stale_job(claimed, monkeypatch):
    _, finish = claimed
    heartbeat_seen = Event()
    def renewal(*args, **kwargs):
        heartbeat_seen.set()
        return False
    monkeypatch.setattr(queue, "renew_lease", renewal)
    def handler(_job, context):
        assert heartbeat_seen.wait(2)
        # The heartbeat can set the event just before marking the lease lost.
        assert context._lost.wait(2)
        context.ensure_active()
    instance = worker.Worker(MagicMock(), {"import": handler}, lease=timedelta(seconds=1), heartbeat=timedelta(milliseconds=10))
    assert instance.run_once()
    finish.assert_not_called()


def test_heartbeat_renews_before_success(claimed, monkeypatch):
    job, finish = claimed
    renewed = Event()
    def renewal(*args, **kwargs):
        renewed.set()
        return True
    monkeypatch.setattr(queue, "renew_lease", renewal)
    def handler(_job, context):
        assert renewed.wait(2)
        context.ensure_active()
    database = MagicMock()
    instance = worker.Worker(database, {"import": handler}, lease=timedelta(seconds=1), heartbeat=timedelta(milliseconds=10))
    assert instance.run_once()
    finish.assert_called_once_with(database, job.id, job.lease_token, success=True, retryable=False)


def test_polling_waits_after_transient_error(monkeypatch):
    instance = worker.Worker(MagicMock(), {"import": MagicMock()})
    monkeypatch.setattr(instance, "run_once", MagicMock(side_effect=RuntimeError("private details")))
    stop = Event()
    def wait(_seconds):
        stop.set()
        return True
    monkeypatch.setattr(stop, "wait", wait)
    instance.run(stop, poll_interval=0.01)
    instance.run_once.assert_called_once_with()


def test_maintenance_failure_does_not_stop_job_processing(monkeypatch):
    stop = Event()
    instance = worker.Worker(MagicMock(), {"import": MagicMock()})
    def process():
        stop.set()
        return True
    monkeypatch.setattr(instance, "run_once", process)
    maintenance = MagicMock(side_effect=RuntimeError("private path"))
    instance.run(stop, maintenance=maintenance)
    maintenance.assert_called_once_with()
    assert stop.is_set()


def test_empty_queue_and_configuration(monkeypatch):
    monkeypatch.setattr(queue, "claim_job", lambda *args, **kwargs: None)
    assert not worker.Worker(MagicMock(), {"import": MagicMock()}).run_once()
    with pytest.raises(ValueError):
        worker.Worker(MagicMock(), {})
    with pytest.raises(ValueError):
        worker.Worker(MagicMock(), {"import": MagicMock()}, lease=timedelta(seconds=1), heartbeat=timedelta(seconds=1))
