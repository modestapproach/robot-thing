"""Belt camera perception with OpenCV (Apache-2.0): colour segmentation + shape classification.

The image comes from MuJoCo's renderer of the fixed ``belt_cam``. Detections are projected from
pixels onto the plane of the item tops using the camera's actual pose and field of view, so the
pick planner receives metric positions in the robot base frame. Ground truth is never read here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import mujoco
import numpy as np

# HSV ranges (OpenCV: H 0-179). Red wraps around 0.
RED_LO1, RED_HI1 = (0, 120, 60), (10, 255, 255)
RED_LO2, RED_HI2 = (170, 120, 60), (179, 255, 255)
BLUE_LO, BLUE_HI = (100, 120, 60), (130, 255, 255)
MIN_AREA_PX = 40


@dataclass
class Detection:
    kind: str            # "red_square" | "blue_circle" | "unknown"
    xy: np.ndarray       # robot-base frame, metres (on the item-top plane)
    yaw: float           # rad, square edge direction (mod pi/2); 0 for circles
    pixel: tuple[float, float]
    area_px: float
    circularity: float


class BeltCamera:
    def __init__(self, model: mujoco.MjModel, data: mujoco.MjData, cam_name: str = "belt_cam", width: int = 320, height: int = 240) -> None:
        self.m, self.d = model, data
        self.cam = model.camera(cam_name).id
        self.W, self.H = width, height
        self.renderer = mujoco.Renderer(model, height, width)
        self.f = (height / 2) / math.tan(math.radians(model.cam_fovy[self.cam]) / 2)

    def rgb(self) -> np.ndarray:
        self.renderer.update_scene(self.d, camera=self.cam)
        return self.renderer.render()

    def pixel_to_world(self, u: float, v: float, plane_z: float) -> np.ndarray:
        """Back-project pixel (u right, v down) to the horizontal plane z = plane_z."""
        ray_cam = np.array([(u - self.W / 2) / self.f, -(v - self.H / 2) / self.f, -1.0])  # MuJoCo cam looks along -z, y up
        R = self.d.cam_xmat[self.cam].reshape(3, 3)
        o = self.d.cam_xpos[self.cam]
        ray = R @ ray_cam
        t = (plane_z - o[2]) / ray[2]
        return (o + t * ray)[:2]

    def detect(self, rgb: np.ndarray, plane_z: float) -> list[Detection]:
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        masks = {
            "red": cv2.inRange(hsv, RED_LO1, RED_HI1) | cv2.inRange(hsv, RED_LO2, RED_HI2),
            "blue": cv2.inRange(hsv, BLUE_LO, BLUE_HI),
        }
        out: list[Detection] = []
        for colour, mask in masks.items():
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                area = cv2.contourArea(c)
                if area < MIN_AREA_PX:
                    continue
                perim = cv2.arcLength(c, True)
                circ = 4 * math.pi * area / (perim * perim) if perim > 0 else 0.0
                (cx, cy), (w, h), ang = cv2.minAreaRect(c)
                square_like = circ < 0.86 and len(cv2.approxPolyDP(c, 0.06 * perim, True)) == 4
                if colour == "red" and square_like:
                    kind = "red_square"
                elif colour == "blue" and not square_like:
                    kind = "blue_circle"
                else:
                    kind = "unknown"
                # image right = +y, image up = -x for belt_cam; convert the rect angle to a world yaw
                yaw = (math.radians(-ang) + math.pi / 2) % (math.pi / 2) if kind == "red_square" else 0.0
                out.append(Detection(kind, self.pixel_to_world(cx, cy, plane_z), yaw, (cx, cy), area, circ))
        return out

    def annotate(self, rgb: np.ndarray, dets: list[Detection], target: Detection | None = None) -> np.ndarray:
        img = np.ascontiguousarray(rgb.copy())
        for dt in dets:
            col = (255, 80, 80) if dt.kind == "red_square" else (80, 140, 255) if dt.kind == "blue_circle" else (255, 255, 0)
            u, v = int(dt.pixel[0]), int(dt.pixel[1])
            r = int(max(6, math.sqrt(dt.area_px) * 0.75))
            cv2.rectangle(img, (u - r, v - r), (u + r, v + r), col, 1)
            cv2.putText(img, "SQ" if dt.kind == "red_square" else "CI" if dt.kind == "blue_circle" else "?", (u - r, v - r - 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, col, 1, cv2.LINE_AA)
        if target is not None:
            u, v = int(target.pixel[0]), int(target.pixel[1])
            cv2.circle(img, (u, v), 3, (255, 255, 255), -1)
        return img
