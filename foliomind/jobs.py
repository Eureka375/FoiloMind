"""Queue task events for consumption by the main thread."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from queue import Empty, Queue
from threading import Event, Thread
from types import MappingProxyType
from uuid import uuid4


class JobState(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class JobRequest:
    kind: str
    scope_id: str | None
    revision: int
    parameters: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class JobEvent:
    job_id: str
    state: JobState
    phase: str
    processed: int = 0
    failed: int = 0
    total: int | None = None


@dataclass(frozen=True)
class Job:
    id: str
    request: JobRequest
    cancellation: Event
    thread: Thread

    def cancel(self) -> None:
        self.cancellation.set()


class JobService:
    def __init__(self) -> None:
        self._events: Queue[JobEvent] = Queue()

    def submit(
        self,
        request: JobRequest,
        phase: str,
        steps: tuple[Callable[[], None], ...],
        *,
        total_known: bool = True,
    ) -> Job:
        job_id = uuid4().hex
        cancellation = Event()
        total = len(steps) if total_known else None

        def run() -> None:
            processed = failed = 0
            self._events.put(JobEvent(job_id, JobState.RUNNING, phase, total=total))
            for step in steps:
                if cancellation.is_set():
                    break
                try:
                    step()
                except Exception:
                    # The GUI receives counts only. Step-specific errors should use safe codes.
                    failed += 1
                processed += 1
                self._events.put(JobEvent(job_id, JobState.RUNNING, phase, processed, failed, total))
            if cancellation.is_set() and processed < len(steps):
                state = JobState.CANCELLED
            elif not failed:
                state = JobState.COMPLETED
            elif failed == processed:
                state = JobState.FAILED
            else:
                state = JobState.PARTIAL
            self._events.put(JobEvent(job_id, state, phase, processed, failed, total))

        thread = Thread(target=run, name=f"foliomind-{job_id}")
        job = Job(job_id, request, cancellation, thread)
        self._events.put(JobEvent(job_id, JobState.QUEUED, phase, total=total))
        thread.start()
        return job

    def drain(self) -> list[JobEvent]:
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except Empty:
                return events
