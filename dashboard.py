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

# Sidebar
st.sidebar.header("Configuration")

# Scenario selection
scenario = st.sidebar.selectbox(
    "Select Scenario",
    options=["CCCscp SfS"],
    help="Choose which test scenario to analyze"
)

st.sidebar.markdown("---")

# File upload
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

# Main area
if uploaded_file is None:
    st.info(
        "📤 **Upload an esmini CSV log** in the sidebar to get started.\n\n"
        "Generate a log with:\n"
        "```bash\n"
        "esmini --osc scenario.xosc --csv_logger run.csv --headless\n"
        "```"
    )
else:
    st.markdown(f"**Scenario:** {scenario} | **File:** {uploaded_file.name}")

    try:
        # Save uploaded file temporarily
        with st.spinner("Analyzing..."):
            temp_path = Path("/tmp") / uploaded_file.name
            temp_path.write_bytes(uploaded_file.getbuffer())

            # Run analysis
            result = plot_sfs(str(temp_path), ego_name=ego_name, target_name=target_name)

        # Results layout
        st.markdown("---")

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
        fig = plt.gcf()

        # Display the figure
        st.pyplot(fig, use_container_width=True)

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
