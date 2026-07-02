"""Thread-safe pipeline runtime: events, cancellation, and run registry."""

import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .run_config import redact_text


class PipelineCancelled(RuntimeError):
    pass


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def is_cancelled(self):
        return self._event.is_set()

    def raise_if_cancelled(self):
        if self.is_cancelled:
            raise PipelineCancelled("用户已请求停止实验")


@dataclass(frozen=True)
class PipelineEvent:
    event_type: str
    stage: str
    message: str
    level: str = "info"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    run_id: str | None = None
    document_name: str | None = None
    completed: int | None = None
    total: int | None = None
    metrics: dict = field(default_factory=dict)


def reduce_events(state, events):
    result = {
        "stage": state.get("stage", "idle"),
        "status": state.get("status", "idle"),
        "document_name": state.get("document_name"),
        "metrics": dict(state.get("metrics", {})),
        "events": list(state.get("events", [])),
        "run_id": state.get("run_id"),
        "document_completed": state.get("document_completed", 0),
        "document_total": state.get("document_total", 0),
        "seen_stages": list(state.get("seen_stages", [])),
    }
    for event in events:
        result["stage"] = event.stage
        if event.stage not in result["seen_stages"]:
            result["seen_stages"].append(event.stage)
        if event.document_name is not None:
            result["document_name"] = event.document_name
        if event.run_id is not None:
            result["run_id"] = event.run_id
        if event.event_type == "started" and event.total is not None:
            result["document_total"] = event.total
        if event.event_type in {"document_completed", "document_failed"}:
            if event.completed is not None:
                result["document_completed"] = event.completed
            if event.total is not None:
                result["document_total"] = event.total
        for name, value in event.metrics.items():
            result["metrics"][name] = result["metrics"].get(name, 0) + value
        result["events"].append(event)
        if event.event_type in {
            "completed",
            "completed_with_errors",
            "cancelled",
            "failed",
        }:
            result["status"] = event.event_type
        elif event.event_type == "started":
            result["status"] = "running"
    result["events"] = result["events"][-200:]
    return result


class PipelineRunRegistry:
    def __init__(self, runner: Callable):
        self._runner = runner
        self._lock = threading.Lock()
        self._thread = None
        self._token = None
        self._events = queue.Queue()
        self._public_config = None

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, config):
        with self._lock:
            if self.is_running:
                raise RuntimeError("已有实验正在运行")
            self._token = CancellationToken()
            self._events = queue.Queue()
            sanitizer = getattr(config, "sanitized_snapshot", None)
            self._public_config = sanitizer() if sanitizer else {}
            self._thread = threading.Thread(
                target=self._run,
                args=(config, self._token),
                daemon=True,
                name="kg-pipeline-worker",
            )
            self._thread.start()

    def _run(self, config, token):
        try:
            self._runner(config, self._events.put, token)
        except PipelineCancelled:
            self._events.put(
                PipelineEvent(
                    "cancelled", "cancelled", "实验已停止", "warning"
                )
            )
        except Exception as exc:
            llm = getattr(config, "llm", None)
            secret = getattr(llm, "api_key", "")
            safe_message = redact_text(str(exc), secrets=(secret,))
            self._events.put(
                PipelineEvent("failed", "failed", safe_message, "error")
            )

    def request_cancel(self):
        if self._token is not None:
            self._token.cancel()

    def drain_events(self):
        items = []
        while True:
            try:
                items.append(self._events.get_nowait())
            except queue.Empty:
                return items

    def snapshot(self):
        return {
            "running": self.is_running,
            "config": dict(self._public_config or {}),
        }

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)
