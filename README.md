# Proactive Data Validation

A Python script for validating records across two CSV datasets and generating an exception report.

## Requirements

- Python 3.9 or later
- No third-party packages required

## Input files

Each CSV file must contain these columns:

```csv
order_id,status,scheduled_at
```

Optional columns: `updated_at`, `source_event_id`.

Use ISO 8601 timestamps with a timezone offset, such as `2026-10-12T23:00:00-04:00`.

## Run

Place the script and input CSV files in the same directory, then run:

```bash
python3 proactive_data_validation.py --sap sample_sap_orders.csv --iq sample_iq_orders.csv
```

To reproduce the sample test at a fixed time:

```bash
python3 proactive_data_validation.py \
  --sap sample_sap_orders.csv \
  --iq sample_iq_orders.csv \
  --now 2026-10-12T23:05:00-04:00
```

## Output

The script prints a validation summary and detected exceptions in the terminal and writes them to `validation_exceptions.csv`.

To specify a different output file:

```bash
python3 proactive_data_validation.py --sap sample_sap_orders.csv --iq sample_iq_orders.csv --output exceptions.csv
```

## Optional arguments

| Argument | Default | Description |
| --- | --- | --- |
| `--grace-minutes` | `30` | Grace period in minutes |
| `--schedule-tolerance-minutes` | `5` | Allowed scheduling difference in minutes |
| `--now` | Current time | Override the validation timestamp (ISO 8601) |
| `--output` | `validation_exceptions.csv` | Output CSV file path |

> The script reads input files and generates reports; it does not modify the source data.
