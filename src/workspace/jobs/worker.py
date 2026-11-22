"""Run registered background-job handlers with renewable leases."""

from collections.abc import Callable, Mapping
from datetime import timedelta
import logging
import json
from time import monotonic
from threading import Event, Thread

from src.workspace.database import WorkspaceDatabase
from src.workspace.jobs import queue


logger = logging.getLogger(__name__)


class PermanentJobError(Exception):
    """An invalid job should fail without another attempt."""


class LeaseLost(Exception):
    """A worker no longer owns its job lease."""


class JobContext:
    """Cooperative lease check for long-running job handlers."""

    def __init__(self, lost: Event) -> None:
        self._lost = lost

    def ensure_active(self) -> None:
        if self._lost.is_set():
            raise LeaseLost("The job lease is no longer active.")


JobHandler = Callable[[queue.ClaimedJob, JobContext], None]


class Worker:
    def __init__(self, database: WorkspaceDatabase, handlers: Mapping[str, JobHandler], *,
                 lease: timedelta = timedelta(minutes=2), heartbeat: timedelta = timedelta(seconds=30), worker_heartbeat=None) -> None:
        if not handlers or any(not key for key in handlers):
            raise ValueError("At least one named handler is required.")
        if heartbeat <= timedelta(0) or lease <= heartbeat:
            raise ValueError("Heartbeat must be positive and shorter than the lease.")
        self.database = database
        self.handlers = dict(handlers)
        self.lease = lease
        self.heartbeat = heartbeat
        self.worker_heartbeat = worker_heartbeat

    def run_once(self) -> bool:
        """Process one claimed job; return false when no job is available.

        Handlers must fence any published results against the lease token inside
        the same database transaction as publication. A cooperative check alone
        cannot prevent a stale worker from publishing after its lease expires.
        """
        job = queue.claim_job(self.database, kinds=tuple(self.handlers), lease=self.lease)
        if job is None:
            return False
        started = monotonic()
        stopped, lost = Event(), Event()

        def keep_alive() -> None:
            while not stopped.wait(self.heartbeat.total_seconds()):
                try:
                    if not queue.renew_lease(self.database, job.id, job.lease_token, lease=self.lease):
                        lost.set()
                        return
                    if self.worker_heartbeat is not None:
                        try:
                            self.worker_heartbeat()
                        except Exception:
                            logger.warning('Worker health update failed.')
                except Exception:
                    logger.warning("Job lease renewal failed.")
                    lost.set()
                    return

        thread = Thread(target=keep_alive, name="workspace-job-heartbeat", daemon=True)
        thread.start()
        success = False
        retryable = False
        try:
            self.handlers[job.kind](job, JobContext(lost))
            success = not lost.is_set()
        except LeaseLost:
            lost.set()
        except PermanentJobError:
            logger.warning("Job failed due to invalid input.")
        except Exception:
            logger.warning("Job failed; it may be retried.")
            retryable = True
        finally:
            stopped.set()
            thread.join()

        if not lost.is_set():
            if not queue.finish_job(self.database, job.id, job.lease_token, success=success, retryable=retryable):
                logger.warning("Job lease expired before completion.")
        logger.info(json.dumps({'event': 'workspace_job_attempt', 'job_id': str(job.id), 'kind': job.kind,
            'attempt': job.attempts, 'outcome': 'lease_lost' if lost.is_set() else 'completed' if success else 'error',
            'retryable': retryable, 'elapsed_seconds': round(monotonic() - started, 3)}))
        return True

    def run(self, stop: Event, *, poll_interval: float = 2.0, maintenance=None, maintenance_interval: float = 3600.0) -> None:
        """Poll until stopped, allowing transient database errors to recover."""
        if poll_interval <= 0 or maintenance_interval <= 0:
            raise ValueError("Poll and maintenance intervals must be positive.")
        next_maintenance = 0.0
        next_heartbeat = 0.0
        while not stop.is_set():
            if self.worker_heartbeat is not None and monotonic() >= next_heartbeat:
                try:
                    self.worker_heartbeat()
                except Exception:
                    logger.warning('Worker health update failed.')
                next_heartbeat = monotonic() + 30
            if maintenance is not None and monotonic() >= next_maintenance:
                try:
                    maintenance()
                except Exception:
                    logger.warning("Workspace maintenance failed; it will be retried.")
                next_maintenance = monotonic() + maintenance_interval
            try:
                processed = self.run_once()
            except Exception:
                logger.warning("Job polling failed; it will be retried.")
                processed = False
            if not processed:
                stop.wait(poll_interval)
