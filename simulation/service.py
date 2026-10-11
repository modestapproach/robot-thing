"""Simulation service API (PRD §7.4). Run: ``uvicorn simulation.service:app --port 8082``.

Agents only see this stable API; the backend (geometric now, MuJoCo/Genesis later)
is hidden behind it.
"""
from __future__ import annotations

import os
from dataclasses import asdict

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from shared.schemas import XY, CalibrationParameters
from simulation.batch import BatchRunner, BatchSpec

app = FastAPI(title="AutoLab Simulation Service")
runner = BatchRunner()
API_KEY = os.environ.get("SIM_SERVICE_KEY", "dev-sim-key")


def auth(x_api_key: str = Header(default="")) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(401, "bad api key")


class EvidencePair(BaseModel):
    target: XY
    observed: XY


class BatchBody(BaseModel):
    batch_id: str | None = None
    twin_version_id: str
    policy_version_id: str = ""
    base_calibration: CalibrationParameters
    candidate_parameters: list[CalibrationParameters]
    evidence: list[EvidencePair]
    scenario_ids: list[str] = []
    random_seeds: list[int] = []
    max_trials: int = 1000
    render_sample_count: int = 0


@app.post("/v1/simulations/batches", dependencies=[Depends(auth)])
def create_batch(b: BatchBody):
    spec = BatchSpec(
        twin_version_id=b.twin_version_id,
        base_calibration=b.base_calibration,
        candidates=b.candidate_parameters,
        evidence=[(e.target, e.observed) for e in b.evidence],
        policy_version_id=b.policy_version_id,
        max_trials=b.max_trials,
        render_sample_count=b.render_sample_count,
        **({"batch_id": b.batch_id} if b.batch_id else {}),
    )
    bid = runner.submit(spec)
    return {"batch_id": bid, "state": "accepted", "status_url": f"/v1/simulations/batches/{bid}"}


@app.get("/v1/simulations/batches/{batch_id}", dependencies=[Depends(auth)])
def get_batch(batch_id: str):
    r = runner.get(batch_id)
    if not r:
        raise HTTPException(404, "unknown batch")
    return asdict(r)


@app.get("/v1/simulations/batches/{batch_id}/artifact", dependencies=[Depends(auth)])
def get_artifact(batch_id: str):
    r = runner.get(batch_id)
    if not r:
        raise HTTPException(404, "unknown batch")
    # Level-0 twin has no renderer; return the best candidate's trajectory as a 2-D polyline reference.
    return {"batch_id": batch_id, "kind": "none", "note": "rendering requires Level-1 backend (MuJoCo/Genesis)"}
