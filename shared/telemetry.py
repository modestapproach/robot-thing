"""Observability facade (PRD §12). One event per meaningful task/batch, spans for steps.

Backends: Raindrop when ``RAINDROP_WRITE_KEY`` is set and the SDK is installed,
otherwise an in-memory recorder (so tests and offline demos still produce traces
that the dashboard can show). Never emits per-physics-step events.
"""
from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from shared.ids import new_id

SIGNALS = {
    "robot_target_missed",
    "twin_prediction_mismatch",
    "unnecessary_retry",
    "candidate_rejected",
    "harness_regression",
    "task_recovered",
}


@dataclass
class Span:
    name: str
    started: float
    ended: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    trace_id: str
    agent: str
    event: str
    input: str
    output: str = ""
    properties: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    signals: list[dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.time)


class _Backend:
    def emit(self, t: Trace) -> None: ...
    def signal(self, trace_id: str, name: str, props: dict[str, Any]) -> None: ...
    def flush(self) -> None: ...


class MemoryBackend(_Backend):
    def __init__(self) -> None:
        self.traces: list[Trace] = []

    def emit(self, t):
        self.traces.append(t)

    def signal(self, trace_id, name, props):
        pass


class RaindropBackend(_Backend):
    """Raindrop adapter (raindrop-ai >= 0.0.56). One ``track_ai`` event per meaningful run,
    keyed by our trace_id so signals and the dashboard link to the same event."""

    NEGATIVE = {"robot_target_missed", "twin_prediction_mismatch", "unnecessary_retry", "candidate_rejected", "harness_regression"}

    def __init__(self, write_key: str) -> None:
        import raindrop.analytics as rd  # pip install raindrop-ai

        self.rd = rd
        rd.init(write_key, tracing_enabled=False, project_id=os.environ.get("RAINDROP_PROJECT_ID") or None)

    def emit(self, t: Trace) -> None:
        import json

        props: dict[str, Any] = {"agent": t.agent}
        for k, v in t.properties.items():
            if isinstance(v, (str, int, float, bool)):
                props[k] = v
        props["spans"] = json.dumps([{"name": s.name, "ms": round((s.ended - s.started) * 1000, 1), **{k: v for k, v in s.attrs.items() if isinstance(v, (str, int, float, bool))}} for s in t.spans])
        props["signals"] = ",".join(x["name"] for x in t.signals)
        self.rd.track_ai(
            user_id="autolab-service", event=t.event, event_id=t.trace_id, model=str(t.properties.get("model", "deterministic")),
            input=t.input, output=t.output or "(no output)", convo_id=t.properties.get("campaign_id") or None, properties=props,
        )

    def signal(self, trace_id: str, name: str, props: dict[str, Any]) -> None:
        flat = {k: v for k, v in props.items() if isinstance(v, (str, int, float, bool))}
        self.rd.track_signal(event_id=trace_id, name=name, signal_type="default", properties=flat,
                             sentiment="NEGATIVE" if name in self.NEGATIVE else "POSITIVE")

    def flush(self) -> None:
        self.rd.flush()


class StoreBackend(_Backend):
    """Mirror each trace into the experiment DB (``agent_traces``) for the dashboard."""

    def __init__(self, store) -> None:
        self.store = store

    def emit(self, t: Trace) -> None:
        self.store.insert("agent_traces", {
            "_id": t.trace_id, "agent": t.agent, "event": t.event, "input": t.input, "output": t.output,
            "properties": {k: v for k, v in t.properties.items() if isinstance(v, (str, int, float, bool, type(None)))},
            "spans": [{"name": s.name, "ms": round((s.ended - s.started) * 1000, 1), **{k: v for k, v in s.attrs.items() if isinstance(v, (str, int, float, bool))}} for s in t.spans],
            "signals": [{"name": x["name"]} for x in t.signals],
            "started": t.started,
            "raindrop": bool(os.environ.get("RAINDROP_WRITE_KEY")),
        })


class Telemetry:
    def __init__(self) -> None:
        self.memory = MemoryBackend()
        self.sink: Optional[_Backend] = None
        self.remote: Optional[_Backend] = None
        key = os.environ.get("RAINDROP_WRITE_KEY")
        if key:
            try:
                self.remote = RaindropBackend(key)
            except Exception as e:  # SDK missing or API mismatch: degrade, never crash the robot loop
                print(f"[telemetry] Raindrop disabled: {e}")

    @contextlib.contextmanager
    def trace(self, agent: str, event: str, input: str, **properties: Any) -> Iterator[Trace]:
        t = Trace(trace_id=new_id("trace"), agent=agent, event=event, input=input, properties=properties)
        try:
            yield t
        except Exception as e:
            t.properties["outcome"] = "error"
            t.properties["error"] = str(e)
            raise
        finally:
            self.memory.emit(t)
            if self.sink:
                try:
                    self.sink.emit(t)
                except Exception as e:
                    print(f"[telemetry] sink failed: {e}")
            if self.remote:
                try:
                    self.remote.emit(t)
                    for s in t.signals:
                        self.remote.signal(t.trace_id, s["name"], s["properties"])
                except Exception as e:
                    print(f"[telemetry] emit failed: {e}")

    @contextlib.contextmanager
    def span(self, t: Trace, name: str, **attrs: Any) -> Iterator[Span]:
        s = Span(name=name, started=time.time(), attrs=attrs)
        try:
            yield s
        finally:
            s.ended = time.time()
            t.spans.append(s)

    def signal(self, t: Trace, name: str, **props: Any) -> None:
        assert name in SIGNALS, name
        t.signals.append({"name": name, "properties": props})

    def flush(self) -> None:
        if self.remote:
            self.remote.flush()

    def attach_store(self, store) -> None:
        self.sink = StoreBackend(store)


telemetry = Telemetry()
