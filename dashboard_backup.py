#!/usr/bin/env python3
"""
scenario-studio: Interactive dashboard for NCAP scenario analysis.

Select a scenario, upload an esmini CSV log, and view analysis results.
"""

import io
import math
from pathlib import Path

import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt

from scenario_studio.analyzers import plot_sfs


# Page configuration
st.set_page_config(
    page_title="scenario-studio",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🧪 scenario-studio")
st.markdown("NCAP Scenario Analysis Dashboard")

# Scenario mapping (scenario name -> folder name)
SCENARIO_MAP = {
    "CCCscp SfS": "cccscp_sfs",
}

# Sidebar
st.sidebar.header("Configuration")

# Scenario selection
scenario = st.sidebar.selectbox(
    "Select Scenario",
    options=list(SCENARIO_MAP.keys()),
    help="Choose which test scenario to analyze"
)

st.sidebar.markdown("---")


# Helper: find CSV logs already sitting in the scenario's reference_data folder
def find_reference_csvs(scenario_name):
    """Return CSV files found in scenarios/<folder>/reference_data/, newest first."""
    scenario_folder = SCENARIO_MAP.get(scenario_name)
    if not scenario_folder:
        return []

    ref_dir = Path("scenarios") / scenario_folder / "reference_data"
    if not ref_dir.exists():
        return []

    csvs = sorted(ref_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return csvs


if st.sidebar.button("🔄 Refresh (rescan reference_data folder)"):
    st.rerun()

auto_csvs = find_reference_csvs(scenario)

# Data source: auto-detected file vs. manual upload
data_source = "Upload manually"
selected_auto_csv = None
uploaded_file = None

if auto_csvs:
    data_source = st.sidebar.radio(
        "CSV source",
        options=["Auto-detected", "Upload manually"],
        help="Auto-detected files are found in scenarios/<scenario>/reference_data/",
    )

    if data_source == "Auto-detected":
        options = [p.name for p in auto_csvs]
        chosen_name = st.sidebar.selectbox(
            "Select CSV",
            options=options,
            help="Most recent file is listed first",
        )
        selected_auto_csv = next(p for p in auto_csvs if p.name == chosen_name)

if data_source == "Upload manually":
    uploaded_file = st.sidebar.file_uploader(
        "Upload esmini CSV log",
        type="csv",
        help="CSV file from: esmini --csv_logger output.csv"
    )

st.sidebar.markdown("---")

# Entity names (optional)
with st.sidebar.expander("Entity Names (optional)"):
    ego_name = st.text_input("Ego entity name", value="Ego")
    target_name = st.text_input("Target entity name", value="Target")


# Helper function to load scenario image
def load_scenario_image(scenario_name):
    """Load scenario image if it exists."""
    scenario_folder = SCENARIO_MAP.get(scenario_name)
    if not scenario_folder:
        return None

    image_path = Path("scenarios") / scenario_folder / "image" / "scenario.png"
    if image_path.exists():
        return image_path
    return None


# Main area
csv_path = None
csv_name = None

if selected_auto_csv is not None:
    csv_path = selected_auto_csv
    csv_name = selected_auto_csv.name
elif uploaded_file is not None:
    # Save uploaded file temporarily so plot_sfs can read it from disk
    temp_path = Path("/tmp") / uploaded_file.name
    temp_path.write_bytes(uploaded_file.getbuffer())
    csv_path = temp_path
    csv_name = uploaded_file.name

if csv_path is None:
    st.info(
        "📤 **No CSV loaded yet.**\n\n"
        "Either upload an esmini CSV log in the sidebar, or drop one into "
        f"`scenarios/{SCENARIO_MAP.get(scenario)}/reference_data/` and it will be "
        "auto-detected.\n\n"
        "Generate a log with:\n"
        "```bash\n"
        "esmini --osc scenario.xosc --csv_logger run.csv --headless\n"
        "```"
    )
else:
    source_label = "auto-detected" if selected_auto_csv is not None else "uploaded"
    st.markdown(f"**Scenario:** {scenario} | **File:** {csv_name} ({source_label})")

    try:
        with st.spinner("Analyzing..."):
            # Run analysis
            result = plot_sfs(str(csv_path), ego_name=ego_name, target_name=target_name)

        # Results layout
        st.markdown("---")

        # Display scenario image if it exists
        scenario_image_path = load_scenario_image(scenario)
        if scenario_image_path:
            st.subheader("Scenario Setup")
            col1, col2 = st.columns([1, 2])
            with col1:
                st.image(str(scenario_image_path), use_container_width=True)
            with col2:
                st.info(
                    f"**{scenario}**\n\n"
                    "This diagram shows the test scenario layout, vehicle positions, "
                    "and relevant geometry for the analysis."
                )
            st.markdown("---")
        else:
            st.warning(f"⚠️ No scenario image found at: `scenarios/{SCENARIO_MAP.get(scenario)}/image/scenario.png`")

        # Verdict banner
        verdict = result["verdict"]
        issues = result["issues"]
        reason = "all protocol criteria met" if not issues else "; ".join(issues)

        if verdict == "PASS":
            st.success(f"✅ **{verdict}** — {reason}")
        else:
            st.error(f"❌ **{verdict}** — {reason}")

        st.markdown("---")

        # Key metrics table
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric(
                "T_Start",
                f"{result['t_start']:.2f} s" if not math.isnan(result['t_start']) else "—"
            )

        with col2:
            st.metric(
                "T_End",
                f"{result['t_end']:.2f} s" if not math.isnan(result['t_end']) else "—"
            )

        with col3:
            st.metric(
                "Impact Time",
                f"{result['t_impact']:.2f} s" if not math.isnan(result['t_impact']) else "—"
            )

        with col4:
            st.metric(
                "Impact Speed",
                f"{result['v_impact']*3.6:.1f} km/h" if not math.isnan(result['v_impact']) else "—"
            )

        # Impact location
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                "Impact Location",
                f"{result['impact_pct']:.1f} %" if not math.isnan(result['impact_pct']) else "—",
                delta="✓ in band" if (not math.isnan(result['impact_pct']) and 25 <= result['impact_pct'] <= 75) else ("✗ out of band" if not math.isnan(result['impact_pct']) else None)
            )

        with col2:
            st.metric(
                "Peak Acceleration",
                f"{max(result['a']):.2f} m/s²" if len(result['a']) > 0 else "—",
                delta="✓ OK" if max(result['a']) <= 1.75 else "✗ exceeds limit"
            )

        st.markdown("---")

        # Graphs
        st.subheader("Analysis Graphs")

        # Get the current figure from matplotlib
        fig = result["figure"]

        # Display the figure
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)

        st.markdown("---")

        # Metadata info
        with st.expander("Scenario Details"):
            meta = result["meta"]
            info_df = pd.DataFrame({
                "Parameter": [
                    "Scenario File",
                    "esmini Version",
                    "esmini Build",
                    "Number of Timesteps",
                    "Time Range"
                ],
                "Value": [
                    Path(meta.get("scenario_file", "?")).name,
                    meta.get("esmini_version", "?"),
                    meta.get("esmini_build", "?"),
                    len(result["t"]),
                    f"{result['t'][0]:.2f} – {result['t'][-1]:.2f} s"
                ]
            })
            st.dataframe(info_df, use_container_width=True, hide_index=True)

        # Issues detail
        if issues:
            with st.expander("Failure Details"):
                for i, issue in enumerate(issues, 1):
                    st.write(f"{i}. {issue}")

    except Exception as e:
        st.error(f"❌ Error analyzing file: {str(e)}")
        st.text(f"Debug info:\n{type(e).__name__}: {e}")

st.markdown("---")
st.markdown(
    "<sub>scenario-studio v0.1.0 | "
    "[GitHub](https://github.com/yourusername/scenario-studio)</sub>",
    unsafe_allow_html=True
)