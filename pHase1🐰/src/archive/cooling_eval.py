# cooling_eval.py
# Purpose:
#   Compare 3 cooling modes (desk / raised / fan) from CSV telemetry
#   using:
#     - elapsed time per condition (seconds)
#     - rolling median smoothing (window configurable)
#     - simple metrics table (plateau, peak, time-to-threshold, variability, AUC)
#
# Assumptions about CSV:
#   - has column "Time" like "2026-02-27_18:07:13" (underscore between date and time)
#   - has column "Temp:PackageId0,0"
#
# Run:
#   python cooling_eval.py

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# =========================
# (A) CONFIG — CHANGE THESE
# =========================

# --- Your 3 input CSV files ---
FILES = {
    "desk":   r"20260227_desk_5min.csv",
    "raised": r"20260227_rised_5min.csv",   # note: your filename uses "rised"
    "fan":    r"20260227_fan_5min.csv",
}

# --- Column names in CSV ---
TIME_COL = "Time"
TEMP_COL = "Temp:PackageId0,0"

# --- Warm-up trimming (ignore first N seconds for some metrics) ---
WARMUP_CUT_S = 10

# --- Plateau window (last N seconds of each test) ---
PLATEAU_LAST_S = 60

# --- Time-to-threshold (pick a temperature that means "already hot") ---
THRESHOLD_C = 90

# --- Smoothing for visualization ---
# IMPORTANT:
#   Your sampling step is ~2 seconds.
#   rolling_window = 50  => about 100 seconds smoothing.
ROLLING_MEDIAN_WINDOW = 50  # <<<<< CHANGE THIS (3 / 5 / 50 etc.)

# --- Plot sizing ---
FIGSIZE = (16, 5)  # wide timeline look


# =========================
# (B) LOADING + PREP
# =========================

def load_one_csv(path: str | Path, condition: str) -> pd.DataFrame:
    """
    Load one CSV and attach condition label.
    Also parse Time into pandas datetime.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path.resolve()}")

    df = pd.read_csv(path)
    if TIME_COL not in df.columns:
        raise KeyError(f"Missing column '{TIME_COL}' in {path.name}")
    if TEMP_COL not in df.columns:
        raise KeyError(f"Missing column '{TEMP_COL}' in {path.name}")

    df["condition"] = condition

    # Time parsing:
    # Example: "2026-02-27_18:07:13" -> "2026-02-27 18:07:13"
    df[TIME_COL] = pd.to_datetime(df[TIME_COL].astype(str).str.replace("_", " ", regex=False))

    return df


def add_seconds_elapsed(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create 'seconds' = elapsed time since start of *each condition*.
    Concept:
      seconds = Time - min(Time within that condition)
    """
    start_time = df.groupby("condition")[TIME_COL].transform("min")
    df["seconds"] = (df[TIME_COL] - start_time).dt.total_seconds()
    return df


# =========================
# (C) METRICS
# =========================

def compute_metrics_for_condition(data: pd.DataFrame) -> dict:
    """
    Compute a small set of metrics for one condition.

    Metrics:
      - plateau_mean_lastN: mean temp over last PLATEAU_LAST_S seconds
      - plateau_std_lastN:  std  temp over last PLATEAU_LAST_S seconds (variability)
      - peak_max_after_warmup: max temp after WARMUP_CUT_S seconds
      - time_to_threshold: first second when temp >= THRESHOLD_C (after warmup)
      - auc_after_warmup: area under temp curve after warmup (°C * sec)
    """
    condition = str(data["condition"].iloc[0])

    # Sort by time just in case (plotting/metrics assume time order)
    data = data.sort_values("seconds")

    # Tail / plateau
    last_sec = float(data["seconds"].max())
    tail = data[data["seconds"] >= last_sec - PLATEAU_LAST_S]
    plateau_mean = float(tail[TEMP_COL].mean())
    plateau_std = float(tail[TEMP_COL].std())

    # Warmup-trimmed segment
    trimmed = data[data["seconds"] >= WARMUP_CUT_S]

    peak_max = float(trimmed[TEMP_COL].max())

    # Time to threshold
    hit = trimmed[trimmed[TEMP_COL] >= THRESHOLD_C]
    time_to_threshold = None if hit.empty else float(hit["seconds"].min())

    # AUC using trapezoid rule (NumPy modern API)
    x = trimmed["seconds"].to_numpy()
    y = trimmed[TEMP_COL].to_numpy()
    auc = None
    if len(x) >= 2:
        auc = float(np.trapezoid(y, x))

    return {
        "condition": condition,
        f"plateau_mean_last{PLATEAU_LAST_S}s_C": plateau_mean,
        f"plateau_std_last{PLATEAU_LAST_S}s_C": plateau_std,
        f"peak_max_after{WARMUP_CUT_S}s_C": peak_max,
        f"time_to_{THRESHOLD_C}C_s": time_to_threshold,
        f"auc_after{WARMUP_CUT_S}s_Cs": auc,
        "duration_total_s": float(last_sec),
    }


# =========================
# (D) PLOTTING
# =========================

def add_rolling_median_column(data: pd.DataFrame, window: int) -> pd.DataFrame:
    """
    Add a smoothed temperature column using rolling median.

    Why rolling median:
      - It "cuts spikes" better than rolling mean.
      - Large window gives "overview mode" (trend),
        small window gives "detail mode".
    """
    data = data.sort_values("seconds").copy()
    sm_col = f"temp_med{window}"
    data[sm_col] = data[TEMP_COL].rolling(window=window).median()
    return data


def plot_three_conditions(df: pd.DataFrame, window: int) -> None:
    """
    One figure, 3 lines, smoothed temp.
    """
    fig, ax = plt.subplots(figsize=FIGSIZE)

    # Style choices: you can change these freely
    styles = {
        "desk":   {"linestyle": "-",  "label": "desk"},
        "raised": {"linestyle": "--", "label": "raised"},
        "fan":    {"linestyle": ":",  "label": "fan"},
    }

    sm_col = f"temp_med{window}"

    for condition, sub in df.groupby("condition"):
        sub = add_rolling_median_column(sub, window=window)

        st = styles.get(condition, {"linestyle": "-", "label": condition})

        ax.plot(
            sub["seconds"],
            sub[sm_col],
            linestyle=st["linestyle"],
            label=st["label"],
        )

    ax.set_xlabel("seconds")
    ax.set_ylabel(f"{TEMP_COL} (rolling median window={window})")
    ax.set_title(f"CPU temp comparison (median{window})")
    ax.legend()
    ax.grid(True, alpha=0.2)

    plt.show()


# =========================
# (E) MAIN
# =========================

def main() -> int:
    # 1) Load 3 CSVs and stack rows (vertical concat)
    frames = []
    for cond, path in FILES.items():
        frames.append(load_one_csv(path, condition=cond))
    cooling_data = pd.concat(frames, ignore_index=True)

    # 2) Add elapsed seconds per condition
    cooling_data = add_seconds_elapsed(cooling_data)

    # 3) Plot (overview)
    plot_three_conditions(cooling_data, window=ROLLING_MEDIAN_WINDOW)

    # 4) Metrics table (per condition)
    rows = []
    for cond, sub in cooling_data.groupby("condition"):
        rows.append(compute_metrics_for_condition(sub))

    results = pd.DataFrame(rows).sort_values("condition").reset_index(drop=True)

    # Pretty print
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)
    print("\n=== RESULTS (per condition) ===")
    print(results.to_string(index=False))

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        raise