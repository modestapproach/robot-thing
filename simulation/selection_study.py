"""Meta-improvement study (PRD §8.6, §14.3): does an experiment-selection policy
reach a target twin accuracy in fewer physical observations?

Both policies face the identical randomized virtual calibration problems. The
metric is observations-to-threshold on held-out (protected) targets, so this
measures the *learning procedure*, not the robot.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from shared.schemas import XY, CalibrationParameters, ExperimentPolicy
from simulation.twin import BOARD_H_MM, BOARD_W_MM, base_to_board, board_to_base, fit_calibration

CANDIDATE_POOL = [XY(x=float(x), y=float(y)) for x in np.linspace(10, BOARD_W_MM - 10, 7) for y in np.linspace(10, BOARD_H_MM - 10, 5)]


def _jac(p: XY) -> np.ndarray:
    # Similarity model params theta = [a, b, tx, ty]; x' = a x - b y + tx ; y' = b x + a y + ty
    return np.array([[p.x, -p.y, 1.0, 0.0], [p.y, p.x, 0.0, 1.0]])


def predictive_variance(p: XY, chosen: list[XY], ridge: float = 1e-3) -> float:
    A = sum((_jac(c).T @ _jac(c) for c in chosen), ridge * np.eye(4))
    J = _jac(p)
    return float(np.trace(J @ np.linalg.inv(A) @ J.T))


def coverage_cell(p: XY, nx: int = 3, ny: int = 2) -> tuple[int, int]:
    return (min(nx - 1, int(p.x / BOARD_W_MM * nx)), min(ny - 1, int(p.y / BOARD_H_MM * ny)))


def choose_next(policy: ExperimentPolicy, chosen: list[XY], rng: np.random.Generator) -> XY:
    remaining = [p for p in CANDIDATE_POOL if p not in chosen]
    if policy.selection == "random" or not chosen:
        return remaining[int(rng.integers(len(remaining)))]
    # Coverage floor: if too few workspace cells are covered, restrict to uncovered cells first.
    covered = {coverage_cell(c) for c in chosen}
    if len(covered) / 6 < policy.coverage_floor:
        unc = [p for p in remaining if coverage_cell(p) not in covered]
        remaining = unc or remaining
    return max(remaining, key=lambda p: predictive_variance(p, chosen))


@dataclass
class StudyResult:
    policy: str
    mean_observations: float
    median_observations: float
    reached_fraction: float
    per_problem: list[int]


def run_study(
    policy: ExperimentPolicy,
    held_out: list[XY],
    n_problems: int = 40,
    threshold_mm: float = 0.6,
    max_obs: int = 20,
    seed: int = 1234,
    act_sigma: float = 0.8,
    obs_sigma: float = 0.4,
) -> StudyResult:
    believed = CalibrationParameters()
    counts: list[int] = []
    reached = 0
    for k in range(n_problems):
        prob_rng = np.random.default_rng(seed + k)  # identical problem for every policy
        truth = CalibrationParameters(
            offset_mm=XY(x=float(prob_rng.uniform(-8, 8)), y=float(prob_rng.uniform(-8, 8))),
            rotation_deg=float(prob_rng.uniform(-2.5, 2.5)),
            scale=float(prob_rng.uniform(0.985, 1.015)),
        )
        noise_rng = np.random.default_rng(seed * 7 + k)
        pick_rng = np.random.default_rng(seed * 13 + k)
        chosen: list[XY] = []
        observed: list[XY] = []
        n_needed = max_obs + 1
        for n in range(1, max_obs + 1):
            p = choose_next(policy, chosen, pick_rng)
            chosen.append(p)
            land = base_to_board(board_to_base(p, believed), truth)
            e = noise_rng.normal(0, 1, 2) * math.hypot(act_sigma, obs_sigma)
            observed.append(XY(x=land.x + float(e[0]), y=land.y + float(e[1])))
            fitted = fit_calibration(chosen, observed, believed)
            # Held-out accuracy: plan with fitted twin, land under truth (noise-free), measure miss.
            errs = [base_to_board(board_to_base(t, fitted), truth).dist(t) for t in held_out]
            rmse = math.sqrt(sum(x * x for x in errs) / len(errs))
            if rmse <= threshold_mm and n >= 3:
                n_needed = n
                reached += 1
                break
        counts.append(n_needed)
    s = sorted(counts)
    return StudyResult(policy.selection, sum(counts) / len(counts), float(s[len(s) // 2]), reached / n_problems, counts)
