"""HTTP client with the Gateway interface, for agents that run off-box (Agent Engine).

The safety envelope, idempotency and e-stop stay in the local gateway service; this
client only forwards requests. Expose the service with an authenticated tunnel
(e.g. ``cloudflared tunnel --url http://127.0.0.1:8081``) and set ROBOT_GATEWAY_URL.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import httpx

from shared.schemas import XY, HardwareCommand, MoveRequest, Observation, RobotState


class RemoteGateway:
    def __init__(self, url: str | None = None, key: str | None = None, timeout_s: float = 20.0, http: httpx.Client | None = None) -> None:
        self.url = (url or os.environ.get("ROBOT_GATEWAY_URL", "")).rstrip("/")
        self.http = http or httpx.Client(timeout=timeout_s)
        self.http.headers["x-api-key"] = key or os.environ.get("ROBOT_GATEWAY_KEY", "")
        st = self.http.get(f"{self.url}/v1/state").raise_for_status().json()
        self.driver = SimpleNamespace(name=st.get("driver", "unknown"), is_physical=bool(st.get("is_physical", False)))  # provenance
        self.robot_id = "robot_main"

    def state(self) -> RobotState:
        d = self.http.get(f"{self.url}/v1/state").raise_for_status().json()
        d.pop("driver", None)
        d.pop("is_physical", None)
        return RobotState.model_validate(d)

    def observe(self) -> Observation:
        return Observation.model_validate(self.http.get(f"{self.url}/v1/observe").raise_for_status().json())

    def submit(self, idempotency_key: str, harness_version_id: str, req: MoveRequest, base_target: XY) -> HardwareCommand:
        body = {"idempotency_key": idempotency_key, "harness_version_id": harness_version_id,
                "request": req.model_dump(mode="json"), "base_target_mm": base_target.model_dump()}
        # Safe to retry: the gateway dedupes on idempotency_key before any motion.
        for attempt in range(3):
            try:
                r = self.http.post(f"{self.url}/v1/commands", json=body)
                return HardwareCommand.model_validate(r.raise_for_status().json())
            except httpx.TransportError:
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")
