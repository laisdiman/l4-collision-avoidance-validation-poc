# Example Data

This directory contains example esmini CSV logs for testing scenario-studio.

## Getting Example Data

To generate example CSV logs:

### CCCscp SfS Scenario

```bash
esmini --osc CCCscp_SfS.xosc \
       --fixed_timestep 0.01 \
       --csv_logger cccscp_sfs_example.csv \
       --headless
```

Then place `cccscp_sfs_example.csv` in this directory.

## Running Tests with Examples

```bash
python -m pytest tests/ -v
```

## Note

Example CSV files are listed in `.gitignore` to avoid committing large log files. Include test fixtures in `tests/` instead.
