"""
Parser for esmini's --csv_logger output.

esmini writes a wide format: a few metadata lines, then one header row in
which every entity contributes its own block of columns, prefixed '#N '.
This module turns that into a tidy long DataFrame with one row per
(timestamp, entity), which is far easier to work with.

Tested against esmini v3.7.2 output.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd


# Columns esmini writes per entity, in order.
_ENTITY_COLS = [
    "entity_name", "entity_id", "speed", "wheel_angle", "wheel_rotation",
    "bb_x", "bb_y", "bb_z", "bb_length", "bb_width", "bb_height",
    "x", "y", "z", "vx", "vy", "vz", "ax", "ay", "az",
    "s", "lateral_distance", "lane_id", "lane_offset",
    "heading", "heading_rate", "rel_heading", "rel_heading_drive_dir",
    "pitch", "road_curvature", "collision_ids",
]

_META_KEYS = {
    "esmini GIT REV": "esmini_rev",
    "esmini GIT TAG": "esmini_version",
    "esmini BUILD VERSION": "esmini_build",
    "Scenario File Name": "scenario_file",
    "Number of Vehicles": "n_entities",
}


def read_esmini_csv(path: str | Path) -> tuple[pd.DataFrame, dict]:
    """
    Read an esmini CSV log.

    Returns
    -------
    df : DataFrame
        One row per (t, entity) with columns from _ENTITY_COLS plus
        'index' and 't'.
    meta : dict
        Provenance: esmini version, build, scenario file.
    """
    path = Path(path)
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()

    # --- metadata block: everything before the column header row ---
    meta: dict[str, str] = {}
    header_idx = None
    for i, line in enumerate(raw):
        if line.lstrip().startswith("Index"):
            header_idx = i
            break
        for key, name in _META_KEYS.items():
            if line.startswith(key):
                meta[name] = line.split(":", 1)[1].strip()
    if header_idx is None:
        raise ValueError(f"No column header row found in {path}")

    n_entities = int(meta.get("n_entities", 0)) or None

    # --- data block ---
    data_lines = [ln for ln in raw[header_idx + 1:] if ln.strip()]
    if not data_lines:
        raise ValueError(f"No data rows in {path}")

    rows = []
    n_per_entity = len(_ENTITY_COLS)
    for ln in data_lines:
        parts = [p.strip() for p in ln.split(",")]
        if parts and parts[-1] == "":
            parts.pop()
        if len(parts) < 2 + n_per_entity:
            continue
        idx, t = parts[0], parts[1]
        body = parts[2:]
        k = n_entities or len(body) // n_per_entity
        if len(body) < k * n_per_entity:
            continue
        for e in range(k):
            chunk = body[e * n_per_entity:(e + 1) * n_per_entity]
            rec = dict(zip(_ENTITY_COLS, chunk))
            rec["index"] = idx
            rec["t"] = t
            rows.append(rec)

    df = pd.DataFrame(rows)

    numeric = [c for c in df.columns if c not in ("entity_name", "collision_ids")]
    for c in numeric:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["collision_ids"] = df["collision_ids"].fillna("").astype(str)
    df = df.sort_values(["t", "entity_id"]).reset_index(drop=True)

    return df[["t", "index", "entity_name", "entity_id"] +
              [c for c in _ENTITY_COLS if c not in ("entity_name", "entity_id")]], meta
