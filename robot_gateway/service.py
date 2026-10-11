"""FastAPI wrapper for the gateway. Run: ``uvicorn robot_gateway.service:app --port 8081``."""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from robot_gateway.camera import MockCamera
from robot_gateway.driver import load_driver
from robot_gateway.gateway import Gateway
from shared.schemas import XY, CalibrationParameters, MoveRequest

app = FastAPI(title="AutoLab Robot Gateway")
API_KEY = os.environ.get("ROBOT_GATEWAY_KEY", "dev-gateway-key")

# Hidden truth for the mock camera: the "real" board is offset/rotated vs. belief.
TRUE_CAL = CalibrationParameters(offset_mm=XY(x=6.0, y=-4.0), rotation_deg=1.5, scale=1.0, calibration_version="truth")
gateway = Gateway(
    driver=load_driver(os.environ.get("ROBOT_DRIVER", "mock")),
    camera=MockCamera(TRUE_CAL),
    robot_id="robot_main",
    physical_enabled=os.environ.get("ROBOT_PHYSICAL_ENABLE", "0") == "1",
)


def auth(x_api_key: str = Header(default="")) -> None:
    if x_api_key != API_KEY:
        raise HTTPException(401, "bad api key")


class SubmitBody(BaseModel):
    idempotency_key: str
    harness_version_id: str
    request: MoveRequest
    base_target_mm: XY


@app.get("/v1/state", dependencies=[Depends(auth)])
def state():
    return {**gateway.state().model_dump(mode="json"), "driver": gateway.driver.name, "is_physical": gateway.driver.is_physical}


@app.get("/v1/observe", dependencies=[Depends(auth)])
def observe():
    return gateway.observe()


@app.post("/v1/commands", dependencies=[Depends(auth)])
def submit(body: SubmitBody):
    return gateway.submit(body.idempotency_key, body.harness_version_id, body.request, body.base_target_mm)


@app.post("/v1/estop", dependencies=[Depends(auth)])
def estop():
    gateway.engage_estop()
    return {"estop": True}
