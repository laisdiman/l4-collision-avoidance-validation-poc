# Quick Start Guide

Get scenario-studio running in 5 minutes.

## Prerequisites

- Python 3.9+
- pip
- esmini (to generate test logs)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/laisdiman/scenario-studio.git
cd scenario-studio
```

### 2. Create virtual environment

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

Or for development:

```bash
pip install -e ".[dev]"
```

## Run the Dashboard

```bash
streamlit run dashboard.py
```

The app will open at `http://localhost:8501`

## Generate Test Data

If you have esmini installed:

```bash
esmini --osc CCCscp_SfS.xosc \
       --fixed_timestep 0.01 \
       --csv_logger test_run.csv \
       --headless
```

Otherwise, use example data from the repository.

## Use the Dashboard

1. **Select Scenario** → "CCCscp SfS"
2. **Upload CSV log** → your generated `test_run.csv`
3. **View Results:**
   - 3-panel analysis graph
   - Key metrics
   - PASS/FAIL verdict
   - Detailed failure reasons (if any)

## What's Next?

- Read the [Full Documentation](../README.md)
- Check the [Architecture Guide](ARCHITECTURE.md)
- Add a new scenario analyzer (see CONTRIBUTING.md)

## Troubleshooting

### "ModuleNotFoundError: No module named 'scenario_studio'"

Make sure you're in the repo root and the package is installed:

```bash
pip install -e .
```

### Streamlit port already in use

Use a different port:

```bash
streamlit run dashboard.py --server.port 8502
```

### CSV parsing errors

Check that:
1. CSV is from esmini with `--csv_logger`
2. File format matches esmini v3.7.2 output
3. File is not truncated or corrupted

### Need help?

Open an issue on GitHub or check the [Contributing Guide](../CONTRIBUTING.md)
