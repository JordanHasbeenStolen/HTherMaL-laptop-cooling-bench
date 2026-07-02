# cooling_dashboard.py
# One-shot dashboard-like script for cooling experiments (CSV -> metrics + plots)
# Works for many conditions: just edit EXPERIMENTS dict.

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


# =========================
# CONFIG (edit here)
# =========================

# Map: condition_name -> csv_path
EXPERIMENTS: Dict[str, str] = {
    "desk":   "20260227_desk_5min.csv",
    "raised": "20260227_rised_5min.csv",
    "fan":    "20260227_fan_5min.csv",

    # Add new tests like this:
    # "usb_left": "20260301_usb_left.csv",
    # "turbo_off": "20260302_turbo_off.csv",
}

TIME_COL = "Time"
TEMP_COL = "Temp:PackageId0,0"
FREQ_COL = "Frequency:Avg"
UTIL_COL = "Util:Avg"

BASELINE = "raised"          # for delta plots/heatmaps
TRIM_SECONDS = 5             # drop warm-up start (seconds)
SMOOTH_MEDIAN_WINDOW = 3     # 1 = no smoothing
BIN_SECONDS = 5              # for heatmaps

PLATEAU_LAST_S = 60          # plateau window at end of each test
THRESHOLD_C = 90             # time-to-threshold

OUT_DIR = Path("out")
OUT_DIR.mkdir(exist_ok=True)


# =========================
# LOADING & PREP
# =========================

def _parse_time_series(df: pd.DataFrame) -> pd.Series:
    """
    Parse Time column from strings like '2026-02-27_18:07:13' or '2026-02-27 18:07:13'
    into pandas datetime.
    """
    if TIME_COL not in df.columns:
        raise ValueError(f"CSV is missing required column '{TIME_COL}'")
    s = df[TIME_COL].astype(str).str.replace("_", " ", regex=False)
    return pd.to_datetime(s, errors="coerce")


def load_experiments(experiments: Dict[str, str]) -> pd.DataFrame:
    """
    Read all CSVs, attach 'condition', parse Time, compute seconds elapsed from
    start of each condition.
    """
    frames: List[pd.DataFrame] = []

    for cond, path in experiments.items():
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"File not found for condition '{cond}': {p.resolve()}")

        df = pd.read_csv(p)
        df["condition"] = cond

        df["Time_dt"] = _parse_time_series(df)

        # seconds elapsed from start inside this condition
        start_time = df["Time_dt"].min()
        df["seconds"] = (df["Time_dt"] - start_time).dt.total_seconds()

        frames.append(df)

    data = pd.concat(frames, ignore_index=True)

    # basic sanity
    if TEMP_COL not in data.columns:
        raise ValueError(f"Missing temperature column '{TEMP_COL}'. Available: {list(data.columns)}")

    return data


def prepare_data(data: pd.DataFrame) -> pd.DataFrame:
    """
    Trim warm-up seconds, sort, optional rolling median smoothing per condition,
    add time bins.
    """
    df = data.copy()

    # keep only rows with valid seconds and temperature
    df = df.dropna(subset=["seconds", TEMP_COL])
    df = df.sort_values(["condition", "seconds"])

    # trim warm-up
    if TRIM_SECONDS > 0:
        df = df[df["seconds"] >= TRIM_SECONDS]

    # smoothing (median)
    if SMOOTH_MEDIAN_WINDOW <= 1:
        df["temp_used"] = df[TEMP_COL]
    else:
        # rolling median per condition; center=True makes it visually nicer
        df["temp_used"] = (
            df.groupby("condition")[TEMP_COL]
              .transform(lambda s: s.rolling(window=SMOOTH_MEDIAN_WINDOW, center=True).median())
        )

    # binning for heatmaps
    df["tbin"] = (df["seconds"] // BIN_SECONDS) * BIN_SECONDS

    return df


# =========================
# METRICS
# =========================

def compute_plateau(df: pd.DataFrame) -> pd.DataFrame:
    """
    Plateau = last PLATEAU_LAST_S seconds for each condition.
    """
    end_sec = df.groupby("condition")["seconds"].transform("max")
    return df[df["seconds"] >= (end_sec - PLATEAU_LAST_S)]


def summary_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Summary stats per condition on plateau, using temp_used.
    """
    plateau = compute_plateau(df)

    summary = (
        plateau.groupby("condition")["temp_used"]
        .agg(
            n="count",
            mean="mean",
            median="median",
            std="std",
            min="min",
            max="max",
        )
        .reset_index()
        .sort_values("median")
    )
    return summary


def time_to_threshold(df: pd.DataFrame) -> pd.DataFrame:
    """
    First seconds where temp_used >= THRESHOLD_C (per condition).
    If never reached -> NaN.
    """
    rows = []
    for cond, g in df.groupby("condition"):
        hit = g[g["temp_used"] >= THRESHOLD_C]
        t = float(hit["seconds"].min()) if not hit.empty else np.nan
        rows.append({"condition": cond, f"time_to_{THRESHOLD_C}C_s": t})
    out = pd.DataFrame(rows).sort_values(f"time_to_{THRESHOLD_C}C_s")
    return out


def correlation_table(df: pd.DataFrame) -> pd.DataFrame:
    """
    Pearson/Spearman correlation per condition for (Temp vs Freq) and (Temp vs Util), if cols exist.
    """
    rows = []
    for cond, g in df.groupby("condition"):
        row = {"condition": cond, "n": len(g)}
        if FREQ_COL in g.columns:
            row["Temp~Freq_pearson"] = g["temp_used"].corr(g[FREQ_COL], method="pearson")
            row["Temp~Freq_spearman"] = g["temp_used"].corr(g[FREQ_COL], method="spearman")
        else:
            row["Temp~Freq_pearson"] = np.nan
            row["Temp~Freq_spearman"] = np.nan

        if UTIL_COL in g.columns:
            row["Temp~Util_pearson"] = g["temp_used"].corr(g[UTIL_COL], method="pearson")
            row["Temp~Util_spearman"] = g["temp_used"].corr(g[UTIL_COL], method="spearman")
        else:
            row["Temp~Util_pearson"] = np.nan
            row["Temp~Util_spearman"] = np.nan

        rows.append(row)

    return pd.DataFrame(rows).sort_values("condition")


# =========================
# PLOTS
# =========================

def savefig(name: str) -> None:
    plt.tight_layout()
    plt.savefig(OUT_DIR / name, dpi=160)
    plt.close()


def plot_line_temp(df: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(12, 4))
    for cond, g in df.groupby("condition"):
        g = g.sort_values("seconds")
        ax.plot(g["seconds"], g["temp_used"], label=cond)
    ax.set_title(f"Temp over time (trim={TRIM_SECONDS}s, median{SMOOTH_MEDIAN_WINDOW}, temp_used)")
    ax.set_xlabel("seconds")
    ax.set_ylabel("Temp (°C)")
    ax.legend()
    savefig("01_line_temp.png")


def plot_heatmap(df: pd.DataFrame) -> None:
    pivot = (
        df.pivot_table(index="condition", columns="tbin", values="temp_used", aggfunc="median")
          .sort_index()
          .sort_index(axis=1)
    )

    fig, ax = plt.subplots(figsize=(12, 3))
    im = ax.imshow(pivot.values, aspect="auto")
    ax.set_title(f"Heatmap median temp_used (bin={BIN_SECONDS}s)")
    ax.set_ylabel("condition")
    ax.set_xlabel("time bin (seconds)")

    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)

    # show ~10 x-ticks max
    step = max(1, pivot.shape[1] // 10)
    xticks = list(range(0, pivot.shape[1], step))
    ax.set_xticks(xticks)
    ax.set_xticklabels([str(int(pivot.columns[i])) for i in xticks])

    fig.colorbar(im, ax=ax, label="°C")
    savefig("02_heatmap_temp.png")


def plot_delta_heatmap(df: pd.DataFrame) -> None:
    if BASELINE not in df["condition"].unique():
        print(f"[WARN] baseline '{BASELINE}' not found; skipping delta heatmap.")
        return

    pivot = (
        df.pivot_table(index="condition", columns="tbin", values="temp_used", aggfunc="median")
          .sort_index()
          .sort_index(axis=1)
    )

    base = pivot.loc[BASELINE]
    delta = pivot.sub(base, axis=1)

    fig, ax = plt.subplots(figsize=(12, 3))
    im = ax.imshow(delta.values, aspect="auto")
    ax.set_title(f"Delta heatmap: (cond - {BASELINE}) (bin={BIN_SECONDS}s)")
    ax.set_ylabel("condition")
    ax.set_xlabel("time bin (seconds)")

    ax.set_yticks(range(len(delta.index)))
    ax.set_yticklabels(delta.index)

    step = max(1, delta.shape[1] // 10)
    xticks = list(range(0, delta.shape[1], step))
    ax.set_xticks(xticks)
    ax.set_xticklabels([str(int(delta.columns[i])) for i in xticks])

    fig.colorbar(im, ax=ax, label="Δ°C")
    savefig("03_heatmap_delta_vs_baseline.png")


def plot_time_to_threshold_bar(t2t: pd.DataFrame) -> None:
    col = f"time_to_{THRESHOLD_C}C_s"
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.bar(t2t["condition"].astype(str), t2t[col])
    ax.set_title(f"Time to reach {THRESHOLD_C}°C (temp_used)")
    ax.set_xlabel("condition")
    ax.set_ylabel("seconds")
    savefig("04_time_to_threshold.png")


def plot_plateau_histograms(df: pd.DataFrame) -> None:
    plateau = compute_plateau(df)

    for cond, g in plateau.groupby("condition"):
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.hist(g["temp_used"].dropna(), bins=10)
        ax.set_title(f"{cond}: plateau temp distribution (last {PLATEAU_LAST_S}s)")
        ax.set_xlabel("Temp (°C)")
        ax.set_ylabel("count")
        savefig(f"05_hist_plateau_{cond}.png")


# =========================
# MAIN
# =========================

def main() -> None:
    data_raw = load_experiments(EXPERIMENTS)
    data = prepare_data(data_raw)

    # tables
    summary = summary_table(data)
    t2t = time_to_threshold(data)
    corr = correlation_table(data)

    summary.to_csv(OUT_DIR / "summary_plateau.csv", index=False)
    t2t.to_csv(OUT_DIR / "time_to_threshold.csv", index=False)
    corr.to_csv(OUT_DIR / "correlations.csv", index=False)

    # plots
    plot_line_temp(data)
    plot_heatmap(data)
    plot_delta_heatmap(data)
    plot_time_to_threshold_bar(t2t)
    plot_plateau_histograms(data)

    print("Done. Outputs saved to:", OUT_DIR.resolve())
    print("\nSummary (plateau):")
    print(summary.to_string(index=False))
    print("\nTime-to-threshold:")
    print(t2t.to_string(index=False))
    print("\nCorrelations:")
    print(corr.to_string(index=False))


if __name__ == "__main__":
    main()