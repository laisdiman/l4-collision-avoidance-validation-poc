# scenario-studio

A modular NCAP scenario analysis tool built with Streamlit. Currently supports CCCscp Start-from-Stop testing with plans to add more scenarios.

## Features

- 🎯 **Interactive Dashboard** — Select scenarios and upload esmini logs via web UI
- 📊 **Multi-panel Analysis** — Drive-away acceleration, speed, and impact location plots
- ✅ **Protocol Compliance** — Automatic checking against CA 102 section 2.3 and impact location bands
- 📈 **Clear Results** — PASS/FAIL verdict with detailed metrics and failure reasons
- 🔧 **Modular Design** — Easy to add new scenarios in `scenario_studio/analyzers/`

## Installation

### 1. Clone or setup the project

```bash
cd scenario-studio
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

## Usage

### 1. Generate an esmini CSV log

```bash
esmini --osc scenario.xosc --fixed_timestep 0.01 \
       --csv_logger run.csv --headless
```

### 2. Run the dashboard

```bash
streamlit run dashboard.py
```

The dashboard will open at `http://localhost:8501` (Streamlit will show the URL).

### 3. Analyze

1. **Select a scenario** (currently: CCCscp SfS)
2. **Upload the CSV log**
3. **View results:**
   - Three-panel analysis graph
   - Key metrics (T_Start, T_End, impact time, speed, location)
   - Verdict (PASS/FAIL) with specific failure reasons
   - Scenario metadata

## Project Structure

```
scenario-studio/
├── dashboard.py                    # Streamlit app entry point
├── requirements.txt                # Python dependencies
├── README.md                       # This file
└── scenario_studio/
    ├── __init__.py
    ├── esmini_log.py              # esmini CSV parser
    └── analyzers/
        ├── __init__.py
        └── sfs.py                 # CCCscp SfS analyzer
```

## CCCscp SfS Analysis

The CCCscp Start-from-Stop analyzer checks two things:

### 1. Drive-away Acceleration (CA 102 section 2.3)

The VUT must maintain specific acceleration thresholds:
- **Before T_Start + 0.5 s**: a ≤ 1.00 m/s²
- **At all times**: a ≤ 1.75 m/s² (absolute limit)
- **After T_Start + 1.25 s**: a > 1.00 m/s²

Where **T_Start** is the time acceleration first exceeds 0.1 m/s² and **T_End** is impact time.

### 2. Impact Location

The GVT must strike the VUT front within the **50% ± 25%** band (25–75% of VUT width).

## Adding New Scenarios

To add a new scenario analyzer:

1. Create `scenario_studio/analyzers/your_scenario.py` with functions:
   - `analyse_your_scenario(csv_path, ...)`  — returns analysis dict
   - `plot_your_scenario(csv_path, ...)` — returns analysis dict and plots

2. Update `scenario_studio/analyzers/__init__.py` to export them

3. Update `dashboard.py`:
   - Add scenario name to `selectbox()` options
   - Handle the new scenario in the analysis logic

## Contributing

This is a work-in-progress. The roadmap includes:
- [ ] More NCAP scenarios (AEB, etc.)
- [ ] Batch analysis and comparison
- [ ] Export results to PDF/HTML
- [ ] Scenario diagram visualization
- [ ] Settings/configuration panel

## License

MIT

## Contact

Built by Lais Diman — lais.diman@outlook.com
