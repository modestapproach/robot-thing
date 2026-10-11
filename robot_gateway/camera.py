"""Camera pipeline interface (PRD §6.5).

``MockCamera`` synthesizes observations from a hidden *true* calibration so the
whole loop runs before the arm exists. ``CharucoCamera`` is the OpenCV path; it
is wired but only loads cv2 when instantiated so the core has no cv2 dependency.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from shared.ids import new_id
from shared.schemas import XY, CalibrationParameters, Observation
from simulation.twin import base_to_board


class Camera(ABC):
    @abstractmethod
    def observe(self, tool_base_mm: XY | None) -> Observation: ...


class MockCamera(Camera):
    """Pretends to see the tool at base_to_board(tool, TRUE calibration) + noise."""

    def __init__(self, truth: CalibrationParameters, observation_sigma_mm: float = 0.4, seed: int = 7) -> None:
        self.truth = truth
        self.sigma = observation_sigma_mm
        self.rng = np.random.default_rng(seed)
        self.board_moved = False
        self.observations = 0

    def observe(self, tool_base_mm):
        self.observations += 1
        if tool_base_mm is None:
            return Observation(board_detected=True, confidence=0.0)
        p = base_to_board(tool_base_mm, self.truth)
        n = self.rng.normal(0.0, self.sigma, 2)
        return Observation(
            board_detected=True,
            board_moved=self.board_moved,
            end_effector_mm=XY(x=p.x + float(n[0]), y=p.y + float(n[1])),
            confidence=0.97,
            image_ref=f"mock://frame/{new_id('img')}",
        )

    def nudge_board(self, dx: float, dy: float, drot_deg: float = 0.0) -> None:
        """Simulate someone bumping the calibration board (changes the TRUE transform)."""
        self.truth = self.truth.model_copy(
            update={
                "offset_mm": XY(x=self.truth.offset_mm.x + dx, y=self.truth.offset_mm.y + dy),
                "rotation_deg": self.truth.rotation_deg + drot_deg,
            }
        )
        self.board_moved = True


class CharucoCamera(Camera):
    """Real pipeline skeleton: detect ChArUco board, homography to F_board, locate tool marker.

    Fill in ``tool_marker_id`` and camera intrinsics once the hardware is mounted.
    Requires ``pip install opencv-contrib-python``.
    """

    def __init__(self, device_index: int = 0, board_json: str = "fixtures/board_a4.json", tool_marker_id: int = 42) -> None:
        import json

        import cv2  # noqa: F401

        self.cv2 = cv2
        self.board_spec = json.load(open(board_json))
        self.tool_marker_id = tool_marker_id
        self.cap = cv2.VideoCapture(device_index)
        d = getattr(cv2.aruco, self.board_spec["aruco_dictionary"])
        self.dictionary = cv2.aruco.getPredefinedDictionary(d)
        self.board = cv2.aruco.CharucoBoard(
            (self.board_spec["squares_x"], self.board_spec["squares_y"]),
            self.board_spec["square_length_mm"],
            self.board_spec["marker_length_mm"],
            self.dictionary,
        )
        self.detector = cv2.aruco.CharucoDetector(self.board)
        self._last_H: np.ndarray | None = None

    def observe(self, tool_base_mm=None):
        cv2 = self.cv2
        ok, frame = self.cap.read()
        if not ok:
            return Observation(board_detected=False, confidence=0.0)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        ch_corners, ch_ids, m_corners, m_ids = self.detector.detectBoard(gray)
        if ch_ids is None or len(ch_ids) < 6:
            return Observation(board_detected=False, confidence=0.0)
        obj = self.board.getChessboardCorners()[ch_ids.flatten()][:, :2]
        H, _ = cv2.findHomography(ch_corners.reshape(-1, 2), obj, cv2.RANSAC, 2.0)
        moved = self._last_H is not None and np.abs(H - self._last_H).max() > 0.05
        self._last_H = H
        tool = None
        conf = 0.0
        if m_ids is not None and self.tool_marker_id in m_ids.flatten():
            i = list(m_ids.flatten()).index(self.tool_marker_id)
            c = m_corners[i].reshape(-1, 2).mean(axis=0)
            v = H @ np.array([c[0], c[1], 1.0])
            tool = XY(x=float(v[0] / v[2]), y=float(v[1] / v[2]))
            conf = min(1.0, len(ch_ids) / 20.0)
        return Observation(board_detected=True, board_moved=moved, end_effector_mm=tool, confidence=conf)
