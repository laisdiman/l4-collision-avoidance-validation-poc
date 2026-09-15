"""
CCCscp Start-from-Stop scenario analyzer.

Checks CA 102 drive-away acceleration corridor and 50% ± 25% impact location.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

from ..esmini_log import read_esmini_csv


# Colors
INK, EGO_C, TGT_C = "#12212B", "#245C87", "#C0561B"
PASS_C, FAIL_C, MUTED, GRID = "#136F4F", "#A81F1A", "#5C6B76", "#DDE3E7"

# CA 102 section 2.3 thresholds
A_EARLY_MAX = 1.00      # before T_Start + 0.5 s
A_ABS_MAX = 1.75        # at all times
A_LATE_MIN = 1.00       # from T_Start + 1.25 s to T_End
T_EARLY = 0.5
T_LATE = 1.25
A_START = 0.1           # defines T_Start


def obb_overlap(a, b) -> bool:
    """Check overlap of two rotated vehicle footprints on a flat road."""

    def corners(r):
        h = float(r["heading"])
        rotation = np.array([
            [math.cos(h), -math.sin(h)],
            [math.sin(h),  math.cos(h)],
        ])

        centre = np.array([r["x"], r["y"]], dtype=float)
        centre += rotation @ np.array(
            [r["bb_x"], r["bb_y"]], dtype=float
        )

        half_l = float(r["bb_length"]) / 2
        half_w = float(r["bb_width"]) / 2

        local = np.array([
            [ half_l,  half_w],
            [ half_l, -half_w],
            [-half_l, -half_w],
            [-half_l,  half_w],
        ])
        return local @ rotation.T + centre

    A, B = corners(a), corners(b)

    for box in (A, B):
        for i in (0, 1):
            edge = box[i + 1] - box[i]
            axis = np.array([-edge[1], edge[0]])

            pa = A @ axis
            pb = B @ axis

            if pa.max() < pb.min() or pb.max() < pa.min():
                return False

    return True

def sfs_impact_pct(E, T):
    """Project the target reference point across the ego front width."""

    def frame(r):
        h = float(r["heading"])
        forward = np.array([math.cos(h), math.sin(h)])
        left = np.array([-math.sin(h), math.cos(h)])

        centre = (
            np.array([r["x"], r["y"]], dtype=float)
            + float(r["bb_x"]) * forward
            + float(r["bb_y"]) * left
        )
        return centre, forward, left

    ec, _, el = frame(E)
    tc, tf, tl = frame(T)

    # Select the target side facing the ego.
    side = 1.0 if np.dot(ec - tc, tl) >= 0 else -1.0

    # Scenario reference: one-quarter length behind the target front,
    # on its side surface.
    target_ref = (
        tc
        + float(T["bb_length"]) / 4 * tf
        + side * float(T["bb_width"]) / 2 * tl
    )

    lateral = float(np.dot(target_ref - ec, el))

    # 0% = ego left edge; 100% = ego right edge.
    return 50.0 - 100.0 * lateral / float(E["bb_width"])


def analyse_sfs(csv_path, ego_name="Ego", target_name="Target") -> dict:
    """
    Analyze a CCCscp SfS run.

    Returns dict with:
    - t, v, a: time, velocity, acceleration arrays
    - t_start, t_end, t_impact: key times
    - v_impact, impact_pct: impact speed, location
    - impact_frame: vehicles at impact
    - verdict: "PASS" or "FAIL"
    - issues: list of failure reasons
    - meta: scenario metadata
    """
    df, meta = read_esmini_csv(csv_path)
    times = np.sort(df["t"].unique())
    by_t = {t: g.set_index("entity_name") for t, g in df.groupby("t")}

    t_arr, v_arr, a_arr = [], [], []
    prev_v = prev_t = None
    t_impact = math.nan
    impact_pct = math.nan
    v_impact = math.nan
    impact_frame = None

    for t in times:
        f = by_t[t]
        if ego_name not in f.index or target_name not in f.index:
            continue
        E, T = f.loc[ego_name], f.loc[target_name]

        # Acceleration from speed trace
        a = 0.0
        if prev_v is not None and t > prev_t:
            a = (E["speed"] - prev_v) / (t - prev_t)
        prev_v, prev_t = E["speed"], t
        t_arr.append(t)
        v_arr.append(E["speed"])
        a_arr.append(a)

        # First contact detection
        if impact_frame is None:
            flagged = str(E.get("collision_ids", "")).strip() not in ("", "nan")
            if flagged or obb_overlap(E, T):
                impact_frame = (E.copy(), T.copy())
                t_impact = float(t)
                v_impact = float(E["speed"])
                # Impact location as % across VUT width (0%=left, 100%=right)
                impact_pct = sfs_impact_pct(E, T)

    t_arr = np.array(t_arr)
    v_arr = np.array(v_arr)
    a_arr = np.array(a_arr)

    # --- T_Start / T_End ---
    idx = np.where(a_arr >= A_START)[0]
    t_start = float(t_arr[idx[0]]) if len(idx) else math.nan
    t_end = t_impact if not math.isnan(t_impact) else float(t_arr[-1])

    # --- Check CA 102 corridor ---
    issues = []
    if not math.isnan(t_start):
        # Early acceleration phase
        m_early = (t_arr >= t_start) & (t_arr < t_start + T_EARLY)
        if m_early.any() and a_arr[m_early].max() > A_EARLY_MAX + 1e-6:
            issues.append(
                f"a = {a_arr[m_early].max():.2f} m/s² before T_Start+0.5 s (limit {A_EARLY_MAX})"
            )
        # Absolute peak
        m_run = (t_arr >= t_start) & (t_arr <= t_end)
        if m_run.any() and a_arr[m_run].max() > A_ABS_MAX + 1e-6:
            issues.append(f"peak a = {a_arr[m_run].max():.2f} m/s² (limit {A_ABS_MAX})")
        # Late acceleration phase
        m_late = (t_arr >= t_start + T_LATE) & (t_arr <= t_end)
        if m_late.any() and a_arr[m_late].min() <= A_LATE_MIN:
            issues.append(
                f"a fell to {a_arr[m_late].min():.2f} m/s² after T_Start+1.25 s (must exceed {A_LATE_MIN})"
            )

    # Check impact location
    impact_ok = (not math.isnan(impact_pct)) and (25.0 <= impact_pct <= 75.0)
    if math.isnan(impact_pct):
        issues.append("no contact recorded")
    elif not impact_ok:
        issues.append(f"impact at {impact_pct:.1f} % of VUT width (band 25-75 %)")

    return {
        "meta": meta,
        "t": t_arr,
        "v": v_arr,
        "a": a_arr,
        "t_start": t_start,
        "t_end": t_end,
        "t_impact": t_impact,
        "v_impact": v_impact,
        "impact_pct": impact_pct,
        "impact_frame": impact_frame,
        "verdict": "FAIL" if issues else "PASS",
        "issues": issues,
    }


def plot_sfs(csv_path, out_png=None, ego_name="Ego", target_name="Target") -> dict:
    """
    Analyze and plot CCCscp SfS run.

    Returns the analysis dict; saves PNG if out_png is provided.
    """
    r = analyse_sfs(csv_path, ego_name, target_name)

    fig = plt.figure(figsize=(13, 4.6))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.15, 1.15, 1], wspace=0.28)

    # --- Panel 1: Acceleration vs CA 102 corridor ---
    ax = fig.add_subplot(gs[0, 0])
    ts, te = r["t_start"], r["t_end"]

    if not math.isnan(ts):
        # Early phase shading
        ax.axvspan(ts, ts + T_EARLY, color="#F0F4F7", zorder=0)
        ax.plot([ts, ts + T_EARLY], [A_EARLY_MAX] * 2, color=FAIL_C, lw=1.4, ls="--")
        ax.plot([ts + T_LATE, te], [A_LATE_MIN] * 2, color=FAIL_C, lw=1.4, ls="--")
        ax.annotate("max before\nT_Start+0.5", (ts + T_EARLY / 2, A_EARLY_MAX),
                    xytext=(0, 6), textcoords="offset points",
                    ha="center", fontsize=7.5, color=FAIL_C)
        ax.annotate("min after T_Start+1.25", ((ts + T_LATE + te) / 2, A_LATE_MIN),
                    xytext=(0, -14), textcoords="offset points",
                    ha="center", fontsize=7.5, color=FAIL_C)

    # Absolute max line
    ax.axhline(A_ABS_MAX, color=FAIL_C, lw=1.4, ls=":")
    ax.annotate(f"absolute max {A_ABS_MAX}", (r["t"][-1], A_ABS_MAX), xytext=(-4, 4),
                textcoords="offset points", ha="right", fontsize=7.5, color=FAIL_C)

    # Plot acceleration
    ax.plot(r["t"], r["a"], color=EGO_C, lw=2)
    if not math.isnan(r["t_impact"]):
        ax.axvline(r["t_impact"], color=MUTED, ls="--", lw=1.2)

    ax.set_xlim(0, max(r["t_end"] * 1.25, 1))
    ax.set_ylim(0, 2.1)
    ax.set_xlabel("t [s]", fontsize=9)
    ax.set_ylabel("a [m/s²]", fontsize=9)
    ax.set_title("Drive-away acceleration vs CA 102 corridor",
                 fontsize=10.5, loc="left", color=INK)
    ax.grid(color=GRID, lw=0.6)
    ax.tick_params(labelsize=8)

    # --- Panel 2: Speed ---
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(r["t"], r["v"] * 3.6, color=EGO_C, lw=2, label="VUT")

    if not math.isnan(r["t_impact"]):
        ax2.axvline(r["t_impact"], color=MUTED, ls="--", lw=1.2)
        ax2.plot([r["t_impact"]], [r["v_impact"] * 3.6], "o", color=EGO_C, ms=6)
        ax2.annotate(f"{r['v_impact']*3.6:.1f} km/h\nat t = {r['t_impact']:.2f} s",
                     (r["t_impact"], r["v_impact"] * 3.6), xytext=(-8, 6),
                     textcoords="offset points", ha="right", fontsize=8, color=EGO_C)

    ax2.set_xlim(0, max(r["t_end"] * 1.25, 1))
    ax2.set_xlabel("t [s]", fontsize=9)
    ax2.set_ylabel("v [km/h]", fontsize=9)
    ax2.set_title("VUT speed at the impact point", fontsize=10.5, loc="left", color=INK)
    ax2.grid(color=GRID, lw=0.6)
    ax2.tick_params(labelsize=8)

    # --- Panel 3: Impact location ---
    ax3 = fig.add_subplot(gs[0, 2])

    if r["impact_frame"] is not None:
        # VUT front bar
        ax3.add_patch(Rectangle((0, -0.18), 100, 0.36, fc="#E8EDF1", ec=INK, lw=1.4))
        # Tolerance band
        ax3.add_patch(Rectangle((25, -0.18), 50, 0.36, fc=PASS_C, alpha=0.16, ec="none"))
        ax3.axvline(50, color=MUTED, ls="--", lw=1.2)
        ax3.annotate("50 % nominal", (50, 0.30), ha="center", fontsize=8, color=MUTED)
        ax3.annotate("25 %", (25, -0.32), ha="center", fontsize=8, color=PASS_C)
        ax3.annotate("75 %", (75, -0.32), ha="center", fontsize=8, color=PASS_C)

        # Impact marker
        pct = r["impact_pct"]
        col = PASS_C if 25 <= pct <= 75 else FAIL_C
        ax3.plot([pct], [0], marker="v", ms=14, color=col, zorder=5)
        ax3.annotate(f"{pct:.1f} %", (pct, 0.10), ha="center", fontsize=10,
                     fontweight="semibold", color=col)

        ax3.set_xlim(-8, 108)
        ax3.set_ylim(-0.55, 0.5)
        ax3.set_xlabel("position across VUT front width [%]", fontsize=9)
    else:
        ax3.text(0.5, 0.5, "no contact recorded", ha="center", va="center",
                 fontsize=11, color=FAIL_C, transform=ax3.transAxes)
        ax3.set_xlim(0, 1)
        ax3.set_ylim(0, 1)

    ax3.set_yticks([])
    ax3.set_title("Impact location, 50 % ± 25 %", fontsize=10.5, loc="left", color=INK)
    ax3.tick_params(labelsize=8)
    for sp in ax3.spines.values():
        sp.set_visible(False)

    # Title and footer
    vcol = PASS_C if r["verdict"] == "PASS" else FAIL_C
    reason = "all protocol criteria met" if not r["issues"] else "; ".join(r["issues"])
    fig.suptitle(f"CCCscp SfS   |   {r['verdict']}   |   {reason}",
                 fontsize=12, x=0.02, ha="left", y=1.02, color=vcol)
    fig.text(0.02, -0.06,
             f"esmini {r['meta'].get('esmini_version','?')} build {r['meta'].get('esmini_build','?')}  |  "
             f"T_Start {r['t_start']:.2f} s, T_End {r['t_end']:.2f} s  |  "
             f"CA 102 section 2.3; impact band 25-75 % of VUT width",
             fontsize=7.5, color=MUTED)

    if out_png:
        fig.savefig(out_png, dpi=140, bbox_inches="tight")

    r["figure"] = fig
    return r
