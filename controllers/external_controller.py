#!/usr/bin/env python3
"""Minimal external Ego controller for the CCCscp SfS scenario.

The OpenSCENARIO file owns the road, Target, initial conditions, and collision
storyboard. This Python process owns Ego motion after the ExternalController is
activated. It writes esmini's normal CSV/log plus a controller-decision CSV.

Run from the project root, for example:

    python controllers/external_controller.py \
      --esmini-bin C:/esmini/esmini-demo/bin

This first controller is deliberately transparent and deterministic. It keeps
the nominal launch acceleration, predicts arrival at the calibrated conflict
point, and applies bounded braking when the predicted arrival times converge.
It is a controller proof-of-concept, not a production AEB algorithm.
"""
from __future__ import annotations

import argparse
import csv
import ctypes as ct
import math
import os
from pathlib import Path


class SEScenarioObjectState(ct.Structure):
    """Layout of esmini's SE_ScenarioObjectState in esmini v3.x."""

    _fields_ = [
        ("id", ct.c_int),
        ("model_id", ct.c_int),
        ("ctrl_type", ct.c_int),
        ("timestamp", ct.c_double),
        ("x", ct.c_double),
        ("y", ct.c_double),
        ("z", ct.c_double),
        ("h", ct.c_double),
        ("p", ct.c_double),
        ("r", ct.c_double),
        ("roadId", ct.c_uint32),
        ("junctionId", ct.c_uint32),
        ("t", ct.c_double),
        ("laneId", ct.c_int),
        ("laneOffset", ct.c_double),
        ("s", ct.c_double),
        ("speed", ct.c_double),
        ("centerOffsetX", ct.c_double),
        ("centerOffsetY", ct.c_double),
        ("centerOffsetZ", ct.c_double),
        ("width", ct.c_double),
        ("length", ct.c_double),
        ("height", ct.c_double),
        ("objectType", ct.c_int),
        ("objectCategory", ct.c_int),
        ("wheel_angle", ct.c_double),
        ("wheel_rot", ct.c_double),
        ("visibilityMask", ct.c_int),
    ]


def parse_args() -> argparse.Namespace:
    project = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description="Run the external Ego controller.")
    p.add_argument("--esmini-bin", type=Path,
                   default=Path(os.environ.get("ESMINI_BIN", r"C:\esmini\esmini-demo\bin")),
                   help="Directory containing esminiLib.dll")
    p.add_argument("--scenario", type=Path,
                   default=project / "scenarios/cccscp_sfs/CCCscp_SfS_external.xosc")
    p.add_argument("--csv-output", type=Path,
                   default=project / "scenarios/cccscp_sfs/reference_data/avoidance_external_01.csv")
    p.add_argument("--event-log", type=Path,
                   default=project / "scenarios/cccscp_sfs/reference_data/avoidance_external_01.log")
    p.add_argument("--controller-log", type=Path,
                   default=project / "scenarios/cccscp_sfs/reference_data/avoidance_controller_01.csv")
    p.add_argument("--ego-index", type=int, default=0)
    p.add_argument("--target-index", type=int, default=1)
    p.add_argument("--dt", type=float, default=None,
                   help="Override ExternalControllerControlPeriod from the scenario")
    p.add_argument("--max-decel", type=float, default=None,
                   help="Override ExternalControllerMaxDecel [m/s²]")
    return p.parse_args()


def load_library(bin_dir: Path):
    dll = (bin_dir / "esminiLib.dll").resolve()
    if not dll.exists():
        raise FileNotFoundError(f"Could not find {dll}")
    # Python 3.8+ needs dependent DLLs to be discoverable explicitly.
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(bin_dir.resolve()))
    se = ct.WinDLL(str(dll))
    se.SE_InitWithArgs.argtypes = [ct.c_int, ct.POINTER(ct.c_char_p)]
    se.SE_InitWithArgs.restype = ct.c_int
    se.SE_StepDT.argtypes = [ct.c_double]
    se.SE_StepDT.restype = ct.c_int
    se.SE_GetQuitFlag.restype = ct.c_int
    se.SE_GetSimulationTime.restype = ct.c_double
    se.SE_GetNumberOfObjects.restype = ct.c_int
    se.SE_GetId.argtypes = [ct.c_int]
    se.SE_GetId.restype = ct.c_uint32
    se.SE_GetObjectState.argtypes = [ct.c_uint32, ct.POINTER(SEScenarioObjectState)]
    se.SE_GetObjectState.restype = ct.c_int
    se.SE_ReportObjectPosXYH.argtypes = [ct.c_uint32, ct.c_double, ct.c_double, ct.c_double]
    se.SE_ReportObjectPosXYH.restype = ct.c_int
    if hasattr(se, "SE_ReportObjectSpeed"):
        se.SE_ReportObjectSpeed.argtypes = [ct.c_uint32, ct.c_double]
        se.SE_ReportObjectSpeed.restype = ct.c_int
    se.SE_GetParameterDouble.argtypes = [ct.c_char_p, ct.POINTER(ct.c_double)]
    se.SE_GetParameterDouble.restype = ct.c_int
    se.SE_Close.restype = None
    return se


def read_double(se, name: str, fallback: float) -> float:
    value = ct.c_double()
    if se.SE_GetParameterDouble(name.encode("utf-8"), ct.byref(value)) == 0:
        return float(value.value)
    return fallback


def get_state(se, object_id: int) -> SEScenarioObjectState:
    state = SEScenarioObjectState()
    if se.SE_GetObjectState(object_id, ct.byref(state)) != 0:
        raise RuntimeError(f"SE_GetObjectState failed for object {object_id}")
    return state


def time_to_conflict(position: float, velocity: float, conflict: float, direction: float) -> float:
    """Return seconds to a one-dimensional conflict coordinate, or infinity."""
    closing_speed = direction * velocity
    remaining = direction * (conflict - position)
    if remaining <= 0.0:
        return 0.0
    if closing_speed <= 1e-6:
        return math.inf
    return remaining / closing_speed


def main() -> int:
    args = parse_args()
    for path in (args.csv_output, args.event_log, args.controller_log):
        path.parent.mkdir(parents=True, exist_ok=True)

    se = load_library(args.esmini_bin)
    command = [
        "external_controller.py",
        "--osc", str(args.scenario.resolve()),
        "--fixed_timestep", "0.01",
        "--csv_logger", str(args.csv_output.resolve()),
        "--logfile_path", str(args.event_log.resolve()),
        "--headless",
    ]
    encoded = [item.encode("utf-8") for item in command]
    argv = (ct.c_char_p * len(encoded))(*encoded)
    if se.SE_InitWithArgs(len(encoded), argv) != 0:
        raise RuntimeError("esmini failed to initialize the external scenario")
    # Enable esmini's API collision reporting in addition to the scenario's
    # OpenSCENARIO CollisionCondition. This can populate collision_ids in the
    # CSV when contact occurs and gives us a second independent check.
    if hasattr(se, "SE_CollisionDetection"):
        se.SE_CollisionDetection.argtypes = [ct.c_bool]
        se.SE_CollisionDetection.restype = None
        se.SE_CollisionDetection(True)

    dt = args.dt or read_double(se, "ExternalControllerControlPeriod", 0.01)
    max_decel = args.max_decel or read_double(se, "ExternalControllerMaxDecel", 6.0)
    max_accel = read_double(se, "ExternalControllerMaxAccel", 1.4)
    conflict_gap = read_double(se, "ExternalControllerConflictGap", 0.75)
    conflict_x = read_double(se, "ExternalControllerConflictX", 255.366)
    conflict_y = read_double(se, "ExternalControllerConflictY", 0.50)
    phase1_accel = read_double(se, "Accel_phase1", 1.0)
    phase1_speed = read_double(se, "Accel_phase1_speed", 0.5)
    nominal_speed = read_double(se, "Accel_targetSpeed", 8.0)

    object_count = se.SE_GetNumberOfObjects()
    if object_count <= max(args.ego_index, args.target_index):
        raise RuntimeError(f"Expected at least two objects, esmini reports {object_count}")
    ego_id = int(se.SE_GetId(args.ego_index))
    target_id = int(se.SE_GetId(args.target_index))
    ego_initial = get_state(se, ego_id)
    ego_x, ego_y, ego_h = ego_initial.x, ego_initial.y, ego_initial.h
    ego_speed = max(0.0, float(ego_initial.speed))
    braking = False

    fields = [
        "time", "ego_x", "ego_y", "ego_speed", "target_x", "target_y",
        "target_speed", "ego_time_to_conflict", "target_time_to_conflict",
        "predicted_time_gap", "risk_detected", "commanded_acceleration",
        "commanded_speed", "controller_mode",
    ]
    try:
        with args.controller_log.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            while se.SE_GetQuitFlag() == 0:
                sim_time = float(se.SE_GetSimulationTime())
                target = get_state(se, target_id)
                ego_t = time_to_conflict(ego_x, ego_speed * math.cos(ego_h), conflict_x, 1.0)
                # The state struct has no velocity fields; the target follows a
                # scripted trajectory, so use its constant speed and direction.
                target_t = time_to_conflict(target.y, -float(target.speed), conflict_y, -1.0)
                gap = abs(ego_t - target_t) if math.isfinite(ego_t) and math.isfinite(target_t) else math.inf
                risk = (not braking and ego_t > 0.0 and ego_t < 5.0 and gap <= conflict_gap)
                if risk:
                    braking = True

                if braking:
                    accel = -max_decel
                    mode = "emergency_brake"
                elif sim_time < 0.5:
                    accel = 0.0
                    mode = "standstill"
                elif ego_speed < phase1_speed:
                    accel = phase1_accel
                    mode = "launch_phase_1"
                else:
                    accel = max_accel
                    mode = "nominal_acceleration"

                next_speed = max(0.0, min(nominal_speed, ego_speed + accel * dt))
                distance = 0.5 * (ego_speed + next_speed) * dt
                next_x = ego_x + distance * math.cos(ego_h)
                next_y = ego_y + distance * math.sin(ego_h)
                se.SE_ReportObjectPosXYH(ego_id, next_x, next_y, ego_h)
                if hasattr(se, "SE_ReportObjectSpeed"):
                    se.SE_ReportObjectSpeed(ego_id, next_speed)

                writer.writerow({
                    "time": f"{sim_time:.6f}",
                    "ego_x": f"{ego_x:.6f}",
                    "ego_y": f"{ego_y:.6f}",
                    "ego_speed": f"{ego_speed:.6f}",
                    "target_x": f"{target.x:.6f}",
                    "target_y": f"{target.y:.6f}",
                    "target_speed": f"{target.speed:.6f}",
                    "ego_time_to_conflict": "" if not math.isfinite(ego_t) else f"{ego_t:.6f}",
                    "target_time_to_conflict": "" if not math.isfinite(target_t) else f"{target_t:.6f}",
                    "predicted_time_gap": "" if not math.isfinite(gap) else f"{gap:.6f}",
                    "risk_detected": str(bool(risk)).lower(),
                    "commanded_acceleration": f"{accel:.6f}",
                    "commanded_speed": f"{next_speed:.6f}",
                    "controller_mode": mode,
                })
                handle.flush()
                ego_x, ego_y, ego_speed = next_x, next_y, next_speed
                if se.SE_StepDT(dt) != 0:
                    raise RuntimeError("SE_StepDT failed")
    finally:
        se.SE_Close()

    print(f"esmini CSV: {args.csv_output}")
    print(f"esmini log: {args.event_log}")
    print(f"controller CSV: {args.controller_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
