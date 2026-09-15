# Architecture

## Overview

scenario-studio is a modular analysis tool for NCAP scenarios. It's designed to be extensible, allowing new scenarios to be added independently.

```
User (Streamlit Dashboard)
    ↓
    dashboard.py
    ↓
    ├── scenario_studio.esmini_log (CSV parsing)
    │
    └── scenario_studio.analyzers
        ├── sfs.py (CCCscp)
        ├── [future: aeb.py]
        ├── [future: ped.py]
        └── ...
```

## Core Modules

### `scenario_studio/esmini_log.py`

Parses esmini `--csv_logger` output into a tidy pandas DataFrame.

**Exports:**
- `read_esmini_csv(path)` → (DataFrame, metadata dict)

**Features:**
- Handles esmini wide format (entity-per-column)
- Extracts metadata (version, build, scenario file)
- Returns long format (one row per entity+time)

### `scenario_studio/analyzers/`

Scenario-specific analysis modules. Each analyzer must implement:

```python
def analyse_<scenario>(csv_path, ego_name="Ego", target_name="Target") -> dict:
    """Run analysis. Returns dict with verdict, issues, metrics, etc."""
    pass

def plot_<scenario>(csv_path, out_png=None, ego_name="Ego", target_name="Target") -> dict:
    """Run analysis and create matplotlib figure. Returns analysis dict."""
    pass
```

**Current Analyzers:**
- `sfs.py` — CCCscp Start-from-Stop (CA 102 corridor, impact location)

**Return Format:**
```python
{
    "verdict": "PASS" or "FAIL",
    "issues": ["list", "of", "failure", "reasons"],
    "t": time_array,
    "v": velocity_array,
    "a": acceleration_array,
    # ... scenario-specific metrics
}
```

### `dashboard.py`

Streamlit application providing the UI.

**Features:**
- Scenario selector
- CSV file upload
- Results display (plots + metrics)
- Error handling

## Adding a New Scenario

### 1. Create analyzer module

File: `scenario_studio/analyzers/my_scenario.py`

```python
from ..esmini_log import read_esmini_csv

def analyse_my_scenario(csv_path, ego_name="Ego", target_name="Target") -> dict:
    df, meta = read_esmini_csv(csv_path)
    
    # Your analysis logic here
    issues = []
    if some_criterion_failed:
        issues.append("reason why it failed")
    
    return {
        "verdict": "FAIL" if issues else "PASS",
        "issues": issues,
        "meta": meta,
        # ... other metrics
    }

def plot_my_scenario(csv_path, out_png=None, ego_name="Ego", target_name="Target") -> dict:
    result = analyse_my_scenario(csv_path, ego_name, target_name)
    
    # Create matplotlib figure
    fig = plt.figure(...)
    # ... plot code
    
    if out_png:
        fig.savefig(out_png, dpi=140, bbox_inches="tight")
    plt.close(fig)
    
    return result
```

### 2. Export from package

Update `scenario_studio/analyzers/__init__.py`:

```python
from .my_scenario import analyse_my_scenario, plot_my_scenario

__all__ = [..., "analyse_my_scenario", "plot_my_scenario"]
```

### 3. Integrate into dashboard

Update `dashboard.py`:

```python
# In sidebar
scenario = st.sidebar.selectbox(
    "Select Scenario",
    options=["CCCscp SfS", "My Scenario"],  # Add here
)

# In main analysis
if scenario == "My Scenario":
    result = plot_my_scenario(str(temp_path), ego_name=ego_name, target_name=target_name)
```

## Data Flow

```
esmini simulation
    ↓
    CSV log (--csv_logger flag)
    ↓
    read_esmini_csv()
    ↓
    DataFrame (long format)
    ↓
    analyse_*() / plot_*()
    ↓
    Results dict + Matplotlib figure
    ↓
    dashboard displays results
```

## Design Decisions

### Why separate `analyse_*` and `plot_*`?

- **Separation of concerns**: Analysis logic is independent of visualization
- **Reusability**: Analysis can be called from CLI, batch scripts, or dashboard
- **Testability**: Easier to unit test analysis without matplotlib

### Why long format DataFrame?

- Easier to filter/group by entity or time
- Works well with pandas operations
- Standard in data science workflows

### Why return analysis dict?

- Contains all information needed for dashboard display
- Extensible for new scenarios (add new fields as needed)
- Easy to serialize to JSON for reporting

## Testing

Tests are in `tests/` directory. Run with:

```bash
pytest -v
```

## Performance Notes

- Current implementation loads entire CSV into memory
- For very large logs (>100k timesteps), consider streaming or chunking
- Matplotlib rendering is cached by Streamlit

## Future Improvements

- [ ] Scenario diagram visualization (top-down geometry)
- [ ] Batch analysis and comparison
- [ ] Export to PDF/HTML reports
- [ ] Support for multiple esmini entity sets
- [ ] Performance optimization for large files
- [ ] Database backend for result storage
