# Contributing to scenario-studio

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

1. Clone the repository:
```bash
git clone https://github.com/laisdiman/scenario-studio.git
cd scenario-studio
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install in development mode with dev dependencies:
```bash
pip install -e ".[dev]"
```

## Adding a New Scenario Analyzer

To add support for a new NCAP scenario:

### 1. Create the analyzer module

Create `scenario_studio/analyzers/your_scenario.py` with:

```python
def analyse_your_scenario(csv_path, ego_name="Ego", target_name="Target") -> dict:
    """Analyze a single run. Returns dict with results."""
    # Implementation
    return {
        "verdict": "PASS" or "FAIL",
        "issues": [...],
        "t": time_array,
        # ... other metrics
    }

def plot_your_scenario(csv_path, out_png=None, ego_name="Ego", target_name="Target") -> dict:
    """Analyze and create matplotlib figure. Returns analysis dict."""
    # Implementation
    return analyse_your_scenario(...)
```

### 2. Export from the analyzers package

Update `scenario_studio/analyzers/__init__.py`:

```python
from .your_scenario import analyse_your_scenario, plot_your_scenario

__all__ = ["analyse_sfs", "plot_sfs", "analyse_your_scenario", "plot_your_scenario"]
```

### 3. Update the dashboard

Edit `dashboard.py` to:
- Add scenario to the selectbox options
- Handle the new scenario in the analysis logic

## Code Style

We use:
- **Black** for code formatting
- **isort** for import sorting
- **mypy** for type checking (optional, but encouraged)

Run before committing:
```bash
black .
isort .
flake8 .
```

## Testing

(Coming soon: pytest test suite)

For now, test manually:
```bash
streamlit run dashboard.py
```

## Commit Messages

Keep commit messages clear and descriptive:
- ✨ feat: Add new scenario analyzer
- 🐛 fix: Correct impact location calculation
- 📝 docs: Update README
- ♻️ refactor: Simplify OBB overlap check
- ✅ test: Add unit tests for metrics

## Pull Requests

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make your changes and commit
3. Push to your fork
4. Open a pull request with a clear description

## Questions?

Open an issue or reach out!
