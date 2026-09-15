#!/usr/bin/env python3
"""Scenario setup and recorded baseline plots for the existing esmini project.

Run from the project root: streamlit run dashboard.py
Uses the existing scenario_studio.esmini_log parser. No analyzer calculations.
Setup edits persist in scenarios/<scenario>/scenario_setup.json.
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import tempfile
import hashlib
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
from PIL import Image
import streamlit as st
import plotly.graph_objects as go

from scenario_studio.esmini_log import read_esmini_csv

ROOT = Path(__file__).resolve().parent
SCENARIO_ROOT = ROOT / "scenarios"


def discover_scenarios() -> dict[str, Path]:
    if not SCENARIO_ROOT.exists():
        return {}

    return {
        folder.name: folder
        for folder in sorted(SCENARIO_ROOT.iterdir())
        if folder.is_dir() and folder.name.lower() != "catalogs"
    }


def discover_recordings(reference_dir: Path) -> list[Path]:
    if not reference_dir.exists():
        return []

    return sorted(
        [
            path for path in reference_dir.glob("*.csv")
            if "controller" not in path.stem.lower()
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
DEFAULT_DESCRIPTION = (
    "Car-to-car crossing, straight crossing path, start from stop. "
    "The ego vehicle starts from standstill and drives straight across the junction. "
    "The target approaches from the farside on a perpendicular path. "
    "This reference baseline uses scripted motion without an avoidance controller."
)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_setup(folder: Path) -> dict:
    path = folder / "scenario_setup.json"
    values = {"description": DEFAULT_DESCRIPTION, "comments": "", "image": "image/scenario.png"}
    if path.exists():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("Saved setup must contain an object.")
        for key in values:
            if key in loaded:
                if not isinstance(loaded[key], str):
                    raise ValueError(f"Saved setup field '{key}' must be text.")
                values[key] = loaded[key]
    return values


def image_path(folder: Path, name: str) -> Path:
    path = (folder / name).resolve()
    if folder.resolve() not in path.parents:
        raise ValueError("The setup image must be inside this scenario folder.")
    return path


def save_setup(folder: Path, current: dict, description: str, comments: str,
               image_bytes: bytes | None = None) -> dict:
    updated = dict(current, description=description.strip(), comments=comments.strip())
    if image_bytes is not None:
        if len(image_bytes) > 10 * 1024 * 1024:
            raise ValueError("Please choose an image smaller than 10 MB.")
        with Image.open(io.BytesIO(image_bytes)) as picture:
            suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}.get(picture.format)
            if suffix is None:
                raise ValueError("Please use a PNG, JPEG, or WebP image.")
            picture.verify()
        filename = "image/setup_" + hashlib.sha256(image_bytes).hexdigest()[:16] + suffix
        atomic_write(image_path(folder, filename), image_bytes)
        updated["image"] = filename
    atomic_write(folder / "scenario_setup.json",
                 json.dumps(updated, ensure_ascii=False, indent=2).encode("utf-8"))
    return updated


def load_csv(path: Path | None, payload: bytes | None):
    if path is not None:
        return read_esmini_csv(path)
    # A platform-independent temporary directory supports Windows uploads too.
    with tempfile.TemporaryDirectory(prefix="scenario_studio_") as temp:
        saved = Path(temp) / "uploaded.csv"
        saved.write_bytes(payload)
        return read_esmini_csv(saved)


def validate_trace(df, ego_name: str):
    if not {"entity_name", "t", "speed", "ax"}.issubset(df.columns):
        raise ValueError("The CSV must include entity name, time, speed, and Acc_X.")
    ego = df.loc[df.entity_name == ego_name].sort_values("t").copy()
    if len(ego) < 2:
        raise ValueError(f"At least two recorded samples are required for '{ego_name}'.")
    if ego.t.duplicated().any():
        raise ValueError("The ego trace contains duplicate timestamps.")
    for column in ("t", "speed", "ax"):
        if not np.isfinite(ego[column].to_numpy(dtype=float)).all():
            raise ValueError(f"The recorded '{column}' column has missing or invalid values.")
    return ego


def recorded_collision_time(ego, log_text: str, csv_name: str) -> tuple[float | None, str]:
    """Positive evidence only. Empty collision fields never imply a PASS."""
    evidence = []
    if "collision_ids" in ego.columns:
        for _, row in ego.iterrows():
            ids = str(row["collision_ids"]).strip()
            if re.search(r"(?<![\d.-])\d+(?![\d.])", ids) and ids not in {"nan", "None"}:
                # ID 0 is a valid actor ID; do not interpret it as an empty value.
                evidence.append((float(row.t), "CSV collision_ids"))
    if log_text:
        # Accept a text log only when its launch options name this CSV.
        options = next((line for line in log_text.splitlines() if "Player options:" in line), "")
        match = re.search(r'--csv_logger\s+(?:"([^"]+)"|(\S+))', options)
        logged_name = (match.group(1) or match.group(2)).replace("\\", "/").split("/")[-1] if match else ""
        if logged_name == csv_name:
            ego_name = str(ego.entity_name.iloc[0])
            pattern = re.compile(r"\[([0-9.]+)\].*\btrue,.*\bcollision\(s\):\s*(.*?)\s*,\s*edge:")
            for line in log_text.splitlines():
                hit = pattern.search(line)
                if not hit:
                    continue
                names = [part.strip() for part in re.split(r"\s+and\s+|,|;", hit.group(2))]
                when = float(hit.group(1))
                if ego_name in names and float(ego.t.min()) <= when <= float(ego.t.max()):
                    evidence.append((when, "paired esmini event log"))
    return min(evidence, key=lambda value: value[0]) if evidence else (None, "")


def baseline_chart(ego, column: str, show: bool, collision_time: float | None,
                   window: tuple[float, float]):
    """Compact AWS-style monitoring panel from unmodified CSV samples."""
    colour = "#73BF69" if column == "speed" else "#E0B400"
    title = "Ego speed" if column == "speed" else "Ego acceleration"
    unit = "m/s" if column == "speed" else "m/s²"
    field_label = "Speed" if column == "speed" else "Acc_X"
    low = min(0.0, float(ego[column].min()))
    high = max(0.0, float(ego[column].max()))
    padding = max((high - low) * .08, .05)
    y_domain = [low - padding, high + padding]
    values = ego.loc[ego.t.between(*window), ["t", column]].to_dict("records") if show else []
    point_values = values[::max(1, math.ceil(len(values) / 32))]
    if values and point_values[-1] != values[-1]:
        point_values.append(values[-1])

    x = alt.X("t:Q", title="Simulation time [s]",
              scale=alt.Scale(domain=list(window), nice=False),
              axis=alt.Axis(tickCount=6, format=".2~f", labelOverlap=True))
    y = alt.Y(f"{column}:Q", title=f"{field_label} [{unit}]",
              scale=alt.Scale(domain=y_domain, nice=False),
              axis=alt.Axis(tickCount=4, format=".3~g"))
    tips = [alt.Tooltip("t:Q", title="Time [s]", format=".6f"),
            alt.Tooltip(f"{column}:Q", title=f"{field_label} [{unit}]", format=".6f")]

    if show:
        line = alt.Chart(alt.Data(values=values)).mark_line(
            color=colour, strokeWidth=1.5, clip=True).encode(x=x, y=y)
        points = alt.Chart(alt.Data(values=point_values)).mark_circle(
            color=colour, size=28, opacity=1, clip=True).encode(x=x, y=y, tooltip=tips)
        layers = [line, points]
    else:
        note = alt.Chart(alt.Data(values=[{"t": sum(window)/2, "value": sum(y_domain)/2}]))
        layers = [note.mark_text(text="Baseline hidden", color="#A9B1BC", fontSize=12).encode(
            x=x, y=alt.Y("value:Q", scale=alt.Scale(domain=y_domain)))]

    if show and collision_time is not None and window[0] <= collision_time <= window[1]:
        event = alt.Chart(alt.Data(values=[{"t": collision_time, "event": "Recorded collision"}]))
        layers.append(event.mark_rule(color="#F28B66", strokeDash=[5, 4], strokeWidth=1.2).encode(
            x=x, tooltip=[alt.Tooltip("event:N", title="Event"),
                          alt.Tooltip("t:Q", title="Time [s]", format=".2f")]))

    return (alt.layer(*layers)
            .properties(height=215, background="#181B1F", padding={"top": 16, "right": 16, "bottom": 16, "left": 16},
                        title=alt.TitleParams(text=title, anchor="start", fontSize=14,
                            color="#E1E5EB", subtitle="Baseline · recorded CSV samples" if show else "Baseline hidden",
                            subtitleColor=colour if show else "#A9B1BC", subtitleFontSize=11,
                            offset=18))
            .configure_view(stroke="#30363D", strokeWidth=1)
            .configure_axis(labelColor="#B8C0CC", titleColor="#B8C0CC", labelFontSize=11,
                            titleFontSize=11, titleFontWeight="normal", titlePadding=10,
                            domainColor="#414852", tickColor="#414852", gridColor="#30363D",
                            gridOpacity=.65, labelPadding=7))


def trajectory_chart(df, show: bool, collision_time: float | None,
                     window: tuple[float, float]):
    """Top-down world-position view of the recorded actors."""
    colours = {"Ego": "#73BF69", "Target": "#6CB6FF"}
    traces = df.loc[df.t.between(*window), ["t", "entity_name", "x", "y"]].copy()
    traces = traces.dropna(subset=["x", "y"])
    names = [name for name in ("Ego", "Target") if name in traces.entity_name.unique()]

    if not show or traces.empty:
        empty = alt.Chart(alt.Data(values=[{"x": 0.0, "y": 0.0}]))
        return (empty.mark_text(text="Baseline hidden", color="#A9B1BC", fontSize=12)
                .encode(x=alt.X("x:Q", title="World X [m]"), y=alt.Y("y:Q", title="World Y [m]"))
                .properties(height=260, background="#181B1F", padding={"top": 16, "right": 16, "bottom": 16, "left": 16},
                            title=alt.TitleParams(text="Actor trajectories", anchor="start", fontSize=14,
                                color="#E1E5EB", subtitle="Baseline hidden", subtitleColor="#A9B1BC",
                                subtitleFontSize=11, offset=18)))

    x_values = traces.x.to_numpy(dtype=float)
    y_values = traces.y.to_numpy(dtype=float)
    x_pad = max((float(x_values.max()) - float(x_values.min())) * .08, .5)
    y_pad = max((float(y_values.max()) - float(y_values.min())) * .08, .5)
    x_domain = [float(x_values.min()) - x_pad, float(x_values.max()) + x_pad]
    y_domain = [float(y_values.min()) - y_pad, float(y_values.max()) + y_pad]

    x = alt.X("x:Q", title="World X [m]", scale=alt.Scale(domain=x_domain, nice=False),
              axis=alt.Axis(tickCount=6, format=".1f", labelOverlap=True))
    y = alt.Y("y:Q", title="World Y [m]", scale=alt.Scale(domain=y_domain, nice=False),
              axis=alt.Axis(tickCount=6, format=".1f", labelOverlap=True))
    tips = [alt.Tooltip("entity_name:N", title="Actor"),
            alt.Tooltip("t:Q", title="Time [s]", format=".2f"),
            alt.Tooltip("x:Q", title="World X [m]", format=".3f"),
            alt.Tooltip("y:Q", title="World Y [m]", format=".3f")]

    sampled_parts = []
    for name in names:
        actor = traces.loc[traces.entity_name == name]
        sampled = actor.iloc[::max(1, math.ceil(len(actor) / 32))]
        if not sampled.empty and sampled.index[-1] != actor.index[-1]:
            sampled = pd.concat([sampled, actor.iloc[[-1]]])
        sampled_parts.append(sampled)
    sampled = pd.concat(sampled_parts, ignore_index=True) if sampled_parts else traces.iloc[0:0]
    colour = alt.Color("entity_name:N", title="Actor",
                       scale=alt.Scale(domain=names, range=[colours.get(name, "#C792EA") for name in names]),
                       legend=alt.Legend(orient="top", symbolSize=70))
    layers = [
        alt.Chart(traces).mark_line(strokeWidth=1.5, clip=True).encode(
            x=x, y=y, color=colour, detail="entity_name:N"),
        alt.Chart(sampled).mark_circle(size=32, opacity=1, clip=True).encode(
            x=x, y=y, color=colour, tooltip=tips),
    ]

    if collision_time is not None:
        event_rows = []
        for name in names:
            actor = df.loc[df.entity_name == name].dropna(subset=["x", "y"])
            if actor.empty:
                continue
            row = actor.loc[[(actor.t - collision_time).abs().idxmin()]]
            event_rows.extend(row.assign(event="Recorded collision").to_dict("records"))
        if event_rows:
            layers.append(alt.Chart(alt.Data(values=event_rows)).mark_point(
                shape="diamond", size=120, filled=True, color="#F28B66", stroke="#FFFFFF", strokeWidth=1
            ).encode(x=x, y=y, tooltip=tips + [alt.Tooltip("event:N", title="Event")]))

    chart = alt.layer(*layers).properties(
        height=260, background="#181B1F", padding={"top": 16, "right": 16, "bottom": 16, "left": 16},
        title=alt.TitleParams(text="Actor trajectories", anchor="start", fontSize=14,
            color="#E1E5EB", subtitle="Baseline · recorded world positions",
            subtitleColor="#73BF69", subtitleFontSize=11, offset=18)
    )
    return (chart.configure_view(stroke="#30363D", strokeWidth=1)
            .configure_axis(labelColor="#B8C0CC", titleColor="#B8C0CC", labelFontSize=11,
                            titleFontSize=11, titleFontWeight="normal", titlePadding=10,
                            domainColor="#414852", tickColor="#414852", gridColor="#30363D",
                            gridOpacity=.65, labelPadding=7)
            .configure_legend(labelColor="#B8C0CC", titleColor="#B8C0CC"))


def comparison_chart(recordings, field, window):
    """Compare recorded samples, grouped by case and actor."""
    trajectory = field == "trajectory"
    case_names = [record["case"] for record in recordings]
    colors = alt.Scale(domain=case_names, scheme="tableau10")

    rows = []
    events = []

    for record in recordings:
        case = record["case"]
        collision = record["collision_time"]

        if trajectory:
            data = record["df"]
            if not {"t", "entity_name", "x", "y"}.issubset(data.columns):
                continue

            visible = data.loc[
                data.t.between(*window),
                ["t", "entity_name", "x", "y"],
            ].copy()
            visible = visible.replace(
                [np.inf, -np.inf], np.nan
            ).dropna(subset=["t", "x", "y"])
        else:
            visible = record["ego"].loc[
                record["ego"].t.between(*window),
                ["t", "entity_name", field],
            ].copy()

        visible["case"] = case
        visible = visible.sort_values("t")
        rows.extend(visible.to_dict("records"))

        if collision is not None and window[0] <= collision <= window[1]:
            if trajectory:
                for _, actor in visible.groupby("entity_name"):
                    nearest = actor.iloc[
                        (actor.t - collision).abs().argmin()
                    ].to_dict()
                    nearest["event"] = (
                        f"Nearest sample to collision at {collision:.3f} s"
                    )
                    events.append(nearest)
            else:
                events.append({
                    "t": collision,
                    "case": case,
                    "event": "Recorded collision",
                })

    if not rows:
        return None

    color = alt.Color(
        "case:N",
        title="Case",
        scale=colors,
        legend=alt.Legend(orient="bottom"),
    )

    tips = [
        alt.Tooltip("case:N", title="Case"),
        alt.Tooltip("entity_name:N", title="Actor"),
        alt.Tooltip("t:Q", title="Time [s]", format=".3f"),
    ]

    if trajectory:
        title = "Actor trajectories"
        x = alt.X(
            "x:Q", title="World X [m]",
            scale=alt.Scale(zero=False),
        )
        y = alt.Y(
            "y:Q", title="World Y [m]",
            scale=alt.Scale(zero=False),
        )
        tips += [
            alt.Tooltip("x:Q", title="World X [m]", format=".3f"),
            alt.Tooltip("y:Q", title="World Y [m]", format=".3f"),
        ]
    else:
        title = "Ego speed" if field == "speed" else "Ego acceleration"
        label = "Speed [m/s]" if field == "speed" else "Acc_X [m/s²]"
        x = alt.X(
            "t:Q",
            title="Simulation time [s]",
            scale=alt.Scale(domain=list(window), nice=False),
        )
        y = alt.Y(f"{field}:Q", title=label)
        tips.append(
            alt.Tooltip(f"{field}:Q", title=label, format=".4f")
        )

    base = alt.Chart(alt.Data(values=rows))
    line = base.mark_line(strokeWidth=2, clip=True).encode(
        x=x,
        y=y,
        color=color,
        detail=["case:N", "entity_name:N"],
        order=alt.Order("t:Q"),
        tooltip=tips,
    )

    if trajectory:
        line = line.encode(
            strokeDash=alt.StrokeDash(
                "entity_name:N",
                title="Actor",
                legend=alt.Legend(orient="bottom"),
            )
        )

    # Sample dots independently for each case and actor.
    samples = []
    frame = pd.DataFrame(rows)
    for _, group in frame.groupby(["case", "entity_name"], sort=False):
        group = group.sort_values("t")
        indices = list(range(0, len(group), max(1, math.ceil(len(group) / 32))))
        if indices[-1] != len(group) - 1:
            indices.append(len(group) - 1)
        samples.extend(group.iloc[indices].to_dict("records"))

    dots = alt.Chart(alt.Data(values=samples)).mark_circle(
        size=30, opacity=1, clip=True,
    ).encode(x=x, y=y, color=color, tooltip=tips)

    layers = [line, dots]

    if events:
        event_chart = alt.Chart(alt.Data(values=events))
        if trajectory:
            marker = event_chart.mark_point(
                shape="diamond", size=130, filled=True,
                stroke="white", strokeWidth=1,
            ).encode(
                x=x, y=y, color=color,
                tooltip=tips + [alt.Tooltip("event:N", title="Event")],
            )
        else:
            marker = event_chart.mark_rule(
                strokeDash=[5, 4], strokeWidth=1.5,
            ).encode(
                x=x, color=color,
                tooltip=[
                    alt.Tooltip("case:N", title="Case"),
                    alt.Tooltip("t:Q", title="Collision time [s]", format=".3f"),
                ],
            )
        layers.append(marker)

    return (
        alt.layer(*layers)
        .properties(
            height=320,
            background="#181B1F",
            title=title,
        )
        .configure_view(stroke="#30363D")
        .configure_axis(
            labelColor="#B8C0CC",
            titleColor="#B8C0CC",
            gridColor="#30363D",
        )
        .configure_title(color="#E1E5EB")
        .configure_legend(
            labelColor="#B8C0CC",
            titleColor="#B8C0CC",
        )
    )

def controller_panels(recordings, window):
    st.subheader("Controller decisions and vehicle response")

    selected_case = st.selectbox(
        "Simulation recording associated with this controller log",
        options=[r["case"] for r in recordings],
        key="controller_case",
    )
    uploaded = st.file_uploader(
        "Controller telemetry CSV",
        type=["csv"],
        key="controller_telemetry",
    )

    if uploaded is None:
        st.info(
            "Upload the controller CSV and select its matching "
            "simulation recording above."
        )
        return

    required = [
        "time",
        "ego_time_to_conflict",
        "target_time_to_conflict",
        "predicted_time_gap",
        "risk_detected",
        "commanded_acceleration",
        "commanded_speed",
        "controller_mode",
    ]

    try:
        controller = pd.read_csv(uploaded, skipinitialspace=True)
        controller.columns = controller.columns.str.strip()

        missing = set(required) - set(controller.columns)
        if missing:
            raise ValueError(
                "Missing columns: " + ", ".join(sorted(missing))
            )

        numeric = [
            "time",
            "ego_time_to_conflict",
            "target_time_to_conflict",
            "predicted_time_gap",
            "commanded_acceleration",
            "commanded_speed",
        ]
        for column in numeric:
            controller[column] = pd.to_numeric(
                controller[column], errors="raise"
            )

        if (
            controller.empty
            or not np.isfinite(controller["time"]).all()
            or controller["time"].duplicated().any()
        ):
            raise ValueError("Expected finite, unique timestamps.")

        risk = (
            controller["risk_detected"]
            .astype(str)
            .str.strip()
            .str.lower()
        )
        if not risk.isin(["true", "false"]).all():
            raise ValueError("risk_detected must contain true or false.")

        controller["risk"] = risk.map({"true": 1, "false": 0})
        controller = controller.sort_values("time")
        controller = controller.replace([np.inf, -np.inf], np.nan)

    except Exception as exc:
        st.error(f"Controller CSV could not be loaded: {exc}")
        return

    record = next(r for r in recordings if r["case"] == selected_case)
    ego = record["ego"]

    overlap_start = max(
        float(ego.t.min()), float(controller.time.min())
    )
    overlap_end = min(
        float(ego.t.max()), float(controller.time.max())
    )
    if overlap_start >= overlap_end:
        st.error("The two files do not have an overlapping time range.")
        return

    visible = controller.loc[
        controller.time.between(*window)
    ].copy()

    if visible.empty:
        st.info("No controller samples in the selected time window.")
        return

    with st.expander("Inspect braking trigger", expanded=True):
        st.dataframe(
            controller.loc[
                controller["time"].between(1.35, 1.80),
                [
                    "time",
                    "ego_time_to_conflict",
                    "target_time_to_conflict",
                    "predicted_time_gap",
                    "risk_detected",
                    "commanded_acceleration",
                    "commanded_speed",
                    "controller_mode",
                ],
            ],
            hide_index=True,
        )

    def draw_series(series, title, unit, key):
        # Use each source's original timestamps; no row-index matching.
        parts = []
        for frame, time_col, value_col, label in series:
            part = frame.loc[
                frame[time_col].between(*window),
                [time_col, value_col],
            ].copy()
            part.columns = ["time", "value"]
            part["signal"] = label
            parts.append(part)

        data = pd.concat(parts, ignore_index=True)
        # JSON null preserves unavailable predictions as missing values.
        values = json.loads(data.to_json(orient="records"))

        chart = (
            alt.Chart(alt.Data(values=values))
            .mark_line(point=True, strokeWidth=2, clip=True)
            .encode(
                x=alt.X(
                    "time:Q",
                    title="Simulation time [s]",
                    scale=alt.Scale(domain=list(window), nice=False),
                ),
                y=alt.Y("value:Q", title=unit),
                color=alt.Color(
                    "signal:N",
                    title=None,
                    legend=alt.Legend(orient="bottom"),
                ),
                strokeDash=alt.StrokeDash("signal:N", legend=None),
                order="time:Q",
                tooltip=[
                    alt.Tooltip("signal:N", title="Signal"),
                    alt.Tooltip("time:Q", title="Time [s]", format=".3f"),
                    alt.Tooltip("value:Q", title=unit, format=".3f"),
                ],
            )
            .properties(title=title, height=260)
        )
        st.altair_chart(chart, key=key)

    left, right = st.columns(2)

    with left:
        draw_series(
            [
                (ego, "t", "speed", "Recorded speed"),
                (controller, "time", "commanded_speed", "Commanded speed"),
            ],
            "Ego speed response",
            "Speed [m/s]",
            "controller_speed_response",
        )

    with right:
        draw_series(
            [
                (ego, "t", "ax", "Recorded Acc_X"),
                (
                    controller, "time", "commanded_acceleration",
                    "Commanded acceleration",
                ),
            ],
            "Ego acceleration response",
            "Acceleration [m/s²]",
            "controller_acceleration_response",
        )

    draw_series(
        [
            (
                controller, "time", "ego_time_to_conflict",
                "Ego time to conflict",
            ),
            (
                controller, "time", "target_time_to_conflict",
                "Target time to conflict",
            ),
            (
                controller, "time", "predicted_time_gap",
                "Predicted time gap",
            ),
        ],
        "Controller conflict predictions",
        "Time [s]",
        "controller_predictions",
    )

    activity = visible[
        ["time", "risk", "controller_mode"]
    ].copy()
    activity["controller_mode"] = activity["controller_mode"].fillna(
        "Unknown"
    )
    activity_data = alt.Data(
        values=json.loads(activity.to_json(orient="records"))
    )
    x = alt.X(
        "time:Q",
        title="Simulation time [s]",
        scale=alt.Scale(domain=list(window), nice=False),
    )
    tips = [
        alt.Tooltip("time:Q", title="Time [s]", format=".3f"),
        alt.Tooltip("risk:Q", title="Risk detected (0/1)"),
        alt.Tooltip("controller_mode:N", title="Mode"),
    ]

    risk_chart = (
        alt.Chart(activity_data)
        .mark_line(interpolate="step-after", color="#F28B66")
        .encode(
            x=x,
            y=alt.Y(
                "risk:Q",
                title="Risk detected",
                scale=alt.Scale(domain=[0, 1]),
                axis=alt.Axis(values=[0, 1]),
            ),
            order="time:Q",
            tooltip=tips,
        )
        .properties(title="Controller risk flag", height=100)
    )
    mode_chart = (
        alt.Chart(activity_data)
        .mark_tick()
        .encode(
            x=x,
            y=alt.Y("controller_mode:N", title="Mode"),
            color=alt.Color("controller_mode:N", legend=None),
            tooltip=tips,
        )
        .properties(title="Controller mode", height=120)
    )

    st.altair_chart(risk_chart, key="controller_risk")
    st.altair_chart(mode_chart, key="controller_modes")

    st.caption(
        "Original timestamps are preserved. Commands and measured responses "
        "may be logged at different points within a simulation step. "
        "Compare commanded acceleration with Acc_X only where the ego "
        "travels along the positive world-X direction."
    )


def vehicle_polygon(row):
    """World-coordinate footprint, including local bounding-box offsets."""
    half_length = float(row.bb_length) / 2
    half_width = float(row.bb_width) / 2

    local = np.array([
        [-half_length, -half_width],
        [ half_length, -half_width],
        [ half_length,  half_width],
        [-half_length,  half_width],
        [-half_length, -half_width],
    ])

    local += [float(row.bb_x), float(row.bb_y)]

    heading = float(row.heading)
    c, s = np.cos(heading), np.sin(heading)
    rotation = np.array([[c, -s], [s, c]])

    return local @ rotation.T + [float(row.x), float(row.y)]


def trajectory_panels(recordings, window, ego_name):
    st.subheader("Vehicle positions")

    required = [
        "t", "x", "y", "heading",
        "bb_x", "bb_y", "bb_length", "bb_width",
    ]
    prepared = []

    for record in recordings:
        df = record["df"].copy()
        missing = set(required + ["entity_name"]) - set(df.columns)

        if missing:
            st.warning(
                f"{record['case']}: missing " + ", ".join(sorted(missing))
            )
            continue

        numeric = df[required].apply(pd.to_numeric, errors="coerce")
        valid = (
            np.isfinite(numeric).all(axis=1)
            & (numeric.bb_length > 0)
            & (numeric.bb_width > 0)
            & df.entity_name.notna()
        )

        if not valid.all():
            st.warning(
                f"{record['case']}: "
                f"{int((~valid).sum())} invalid position samples omitted."
            )

        df[required] = numeric
        df = df.loc[valid].sort_values("t")

        if not df.empty:
            prepared.append((record, df))

    if not prepared:
        st.info("No valid vehicle positions available.")
        return

    # Fixed shared bounds from every valid sample and vehicle footprint.
    # Bounding circles provide inexpensive, conservative outline bounds.
    bounds = []
    for _, df in prepared:
        c = np.cos(df.heading)
        s = np.sin(df.heading)
        cx = df.x + c * df.bb_x - s * df.bb_y
        cy = df.y + s * df.bb_x + c * df.bb_y
        radius = np.hypot(df.bb_length, df.bb_width) / 2

        bounds.append([
            float((cx - radius).min()),
            float((cx + radius).max()),
            float((cy - radius).min()),
            float((cy + radius).max()),
        ])

    bounds = np.array(bounds)
    xmin, xmax = bounds[:, 0].min(), bounds[:, 1].max()
    ymin, ymax = bounds[:, 2].min(), bounds[:, 3].max()

    # Square world-coordinate extent, identical for every case.
    span = max(xmax - xmin, ymax - ymin) + 4
    center_x = (xmin + xmax) / 2
    center_y = (ymin + ymax) / 2
    x_range = [center_x - span / 2, center_x + span / 2]
    y_range = [center_y - span / 2, center_y + span / 2]

    low, high = map(float, window)
    if low >= high:
        st.info("Select a time window with different endpoints.")
        return

    slider_key = hashlib.sha256(
        repr((
            [
                (
                    r["case"], len(df),
                    float(df.t.min()), float(df.t.max()),
                )
                for r, df in prepared
            ],
            low, high,
        )).encode()
    ).hexdigest()[:16]

    selected_time = st.slider(
        "Inspect vehicle positions at time [s]",
        min_value=low,
        max_value=high,
        value=low,
        step=0.01,
        format="%.2f",
        key=f"vehicle_time_{slider_key}",
    )

    trail_seconds = st.slider(
        "Trail length [s]",
        min_value=0.0,
        max_value=5.0,
        value=1.0,
        step=0.25,
        key="vehicle_trail_length",
    )

    names = sorted({
        str(name)
        for _, df in prepared
        for name in df.entity_name.unique()
    })
    palette = ["#C792EA", "#66D9A8", "#F4D35E", "#EF83B9"]
    colors = {name: palette[i % len(palette)] for i, name in enumerate(names)}
    colors["Target"] = "#FFAA44"
    colors[ego_name] = "#58B5FF"

    # At most two cases per row.
    for offset in range(0, len(prepared), 2):
        pair = prepared[offset:offset + 2]
        columns = st.columns(2)

        for column, (record, df) in zip(columns, pair):
            with column:
                st.markdown(f"**{record['case']}**")
                fig = go.Figure()
                status = []

                for name, actor in df.groupby("entity_name", sort=False):
                    actor = actor.sort_values("t")
                    first = float(actor.t.iloc[0])
                    last = float(actor.t.iloc[-1])

                    if selected_time < first:
                        status.append(f"{name}: recording not started")
                        continue

                    # Hold the last recorded pose after the actor log ends.
                    pose_time = min(selected_time, last)
                    available = actor.loc[actor.t <= pose_time]
                    row = available.iloc[-1]

                    ended = selected_time > last + 1e-9
                    if ended:
                        status.append(
                            f"{name}: recording ended at {last:.2f} s; "
                            "final pose shown"
                        )

                    color = colors[str(name)]
                    polygon = vehicle_polygon(row)

                    if trail_seconds > 0:
                        trail = actor.loc[
                            actor.t.between(
                                max(first, pose_time - trail_seconds),
                                pose_time,
                            )
                        ]
                        # Trail follows the bounding-box center.
                        c = np.cos(trail.heading)
                        s = np.sin(trail.heading)
                        tx = trail.x + c * trail.bb_x - s * trail.bb_y
                        ty = trail.y + s * trail.bb_x + c * trail.bb_y

                        fig.add_trace(go.Scatter(
                            x=tx, y=ty,
                            mode="lines",
                            line=dict(color=color, width=2),
                            opacity=0.35,
                            showlegend=False,
                            hoverinfo="skip",
                        ))

                    fig.add_trace(go.Scatter(
                        x=polygon[:, 0],
                        y=polygon[:, 1],
                        mode="lines",
                        fill="toself",
                        name=str(name),
                        line=dict(color=color, width=2),
                        opacity=0.4 if ended else 0.85,
                        text=[f"Recorded sample: {row.t:.3f} s"] * 5,
                        hovertemplate=(
                            "%{text}<br>"
                            "World X: %{x:.2f} m<br>"
                            "World Y: %{y:.2f} m"
                            "<extra>%{fullData.name}</extra>"
                        ),
                    ))

                    # White front edge indicates vehicle orientation.
                    fig.add_trace(go.Scatter(
                        x=polygon[1:3, 0],
                        y=polygon[1:3, 1],
                        mode="lines",
                        line=dict(color="#FFFFFF", width=4),
                        showlegend=False,
                        hoverinfo="skip",
                    ))

                fig.update_layout(
                    template="plotly_dark",
                    height=440,
                    margin=dict(l=45, r=15, t=15, b=45),
                    paper_bgcolor="#181B1F",
                    plot_bgcolor="#181B1F",
                    legend=dict(orientation="h", y=1.08, x=0),
                    xaxis=dict(
                        title="World X [m]",
                        range=x_range,
                        constrain="domain",
                        fixedrange=True,
                        zeroline=False,
                        gridcolor="#2C333D",
                    ),
                    yaxis=dict(
                        title="World Y [m]",
                        range=y_range,
                        scaleanchor="x",
                        scaleratio=1,
                        constrain="domain",
                        fixedrange=True,
                        zeroline=False,
                        gridcolor="#2C333D",
                    ),
                )

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                    theme=None,
                    key=f"vehicle_scene_{offset}_{record['case']}",
                    config={"displayModeBar": False},
                )

                for message in status:
                    st.caption(message)

    st.caption(
        "Vehicle bounding boxes in a top-down coordinate view. "
        "White edges indicate the front. Each pose uses the latest "
        "recorded sample at or before the selected time; no interpolation. "
        "All cases use identical bounds and equal X/Y scaling."
    )

def main():
    st.set_page_config(
        page_title="Scenario Studio",
        page_icon="🚘",
        layout="wide",
    )
    st.title("Scenario Studio")

    with st.sidebar:
        st.header("Simulation recording")

        scenario_dirs = discover_scenarios()
        if not scenario_dirs:
            st.error("No scenario folders found.")
            st.stop()

        scenario = st.selectbox("Scenario", list(scenario_dirs.keys()))
        ego_name = st.text_input("Ego entity name", value="Ego")

    folder = scenario_dirs[scenario]
    reference_dir = folder / "reference_data"

    if st.button("Refresh recordings"):
        st.rerun()

    csvs = discover_recordings(reference_dir)
    source = st.radio("CSV source", ["Project recordings", "Upload CSV"])

    selected_csvs = []
    payload = None
    csv_name = ""
    log_text = ""

    if source == "Project recordings":
        if csvs:
            case_names = [path.stem for path in csvs]
            selected_cases = st.multiselect(
                "Cases to compare",
                options=case_names,
                default=case_names,
            )
            selected_csvs = [
                path for path in csvs
                if path.stem in selected_cases
            ]
        else:
            st.info("No CSV recordings found.")
    else:
        uploaded = st.file_uploader("Simulation CSV", type=["csv"])
        if uploaded:
            payload = uploaded.getvalue()
            csv_name = uploaded.name

        log_upload = st.file_uploader(
            "Matching esmini event log (optional)",
            type=["log", "txt"],
        )
        if log_upload:
            log_text = log_upload.getvalue().decode(
                "utf-8",
                errors="replace",
            )

    st.subheader("Recording comparison")
    st.caption(
        "Recorded esmini samples. Acc_X is world-X acceleration; "
        "it represents longitudinal acceleration for an X-aligned ego path."
    )

    inputs = []
    if source == "Project recordings":
        inputs = [(path, None, path.name) for path in selected_csvs]
    elif payload is not None:
        inputs = [(None, payload, csv_name)]

    if not inputs:
        st.info("Select at least one recording or upload a CSV.")
        return

    recordings = []

    for path, content, name in inputs:
        try:
            df, meta = load_csv(path, content)
            ego = validate_trace(df, ego_name)

            # Each recording must use its own matching log.
            case_log = log_text if path is None else ""
            if path is not None:
                paired_log = path.with_suffix(".log")
                if paired_log.exists():
                    case_log = paired_log.read_text(
                        encoding="utf-8", errors="replace",
                    )

            collision, evidence = recorded_collision_time(
                ego, case_log, name,
            )

            recordings.append({
                "case": Path(name).stem,
                "csv": name,
                "df": df,
                "ego": ego,
                "meta": meta,
                "collision_time": collision,
                "evidence": evidence,
            })

        except Exception as exc:
            st.error(f"{name}: INVALID — {exc}")

    if not recordings:
        return

    details = []
    for record in recordings:
        ego = record["ego"]
        collision = record["collision_time"]
        details.append({
            "Case": record["case"],
            "Outcome": (
                "FAIL — recorded collision"
                if collision is not None
                else "Not assessed"
            ),
            "Collision time [s]": collision,
            "Evidence": record["evidence"],
            "Ego samples": len(ego),
            "Start [s]": float(ego.t.min()),
            "End [s]": float(ego.t.max()),
        })

    st.dataframe(pd.DataFrame(details), hide_index=True)
    st.caption(
        "No recorded collision does not establish PASS. "
        "Run completion and validity must also be verified."
    )

    start = min(float(r["ego"].t.min()) for r in recordings)
    end = max(float(r["ego"].t.max()) for r in recordings)

    # Reset the window when the selected recordings or their bounds change.
    window_id = hashlib.sha256(
        repr([
            (
                r["case"],
                float(r["ego"].t.min()),
                float(r["ego"].t.max()),
                len(r["ego"]),
            )
            for r in recordings
        ]).encode("utf-8")
    ).hexdigest()[:16]

    time_window = st.slider(
        "Time window for all graphs [s]",
        min_value=start,
        max_value=end,
        value=(start, end),
        step=.01,
        format="%.2f",
        key=f"comparison_window_{scenario}_{ego_name}_{window_id}",
    )

    if time_window[0] >= time_window[1]:
        st.info("Select different start and end times.")
        return

    chart_columns = st.columns(2)
    for chart_col, field in zip(chart_columns, ("speed", "ax")):
        with chart_col:
            chart = comparison_chart(recordings, field, time_window)
            if chart is None:
                st.info("No samples in this time window.")
            else:
                st.altair_chart(
                    chart, theme=None, key=f"comparison_{field}",
                )

    trajectory_panels(recordings, time_window, ego_name)

    controller_panels(recordings, time_window)

    with st.expander("Recording details"):
        for record in recordings:
            st.write({
                "CSV": record["csv"],
                "Ego": ego_name,
                "Samples": len(record["ego"]),
                "esmini version": record["meta"].get(
                    "esmini_version", "Unknown",
                ),
                "Scenario file": record["meta"].get(
                    "scenario_file", "Unknown",
                ),
            })











if __name__ == "__main__":
    main()
