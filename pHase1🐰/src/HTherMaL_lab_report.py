# thermal_lab_report.py
# One-shot HTML report generator for cooling experiments
# CSV -> prep (seconds/trim/smooth/bin) -> metrics -> plots -> single HTML report

from __future__ import annotations

from pathlib import Path
from typing import Dict, List
from io import BytesIO
import base64
import html

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


# =========================
# CONFIG (edit here)
# =========================

EXPERIMENTS: Dict[str, str] = {
    "desk":   "20260227_desk_5min.csv",
    "raised": "20260227_rised_5min.csv",
    "fan":    "20260227_fan_5min.csv",

    # add new ones like:
    # "usb_left": "20260301_usb_left.csv",
    # "turbo_off": "20260302_turbo_off.csv",
}

TIME_COL = "Time"
TEMP_COL = "Temp:PackageId0,0"
FREQ_COL = "Frequency:Avg"
UTIL_COL = "Util:Avg"

BASELINE = "raised"          # for delta heatmap
TRIM_SECONDS = 5             # cut warm-up
SMOOTH_MEDIAN_WINDOW = 3     # 1 = no smoothing
BIN_SECONDS = 5              # for heatmaps
PLATEAU_LAST_S = 60          # plateau window at end
THRESHOLD_C = 90             # time-to-threshold

OUT_DIR = Path("out")
OUT_DIR.mkdir(exist_ok=True)

REPORT_PATH = OUT_DIR / "thermal_report.html"


# =========================
# UTIL: plotting to base64
# =========================

def fig_to_base64_png(fig) -> str:
    """Convert a matplotlib figure to base64-encoded PNG (for embedding in HTML)."""
    buf = BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=160)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


# =========================
# LOADING & PREP
# =========================

def _parse_time_series(df: pd.DataFrame) -> pd.Series:
    if TIME_COL not in df.columns:
        raise ValueError(f"CSV is missing required column '{TIME_COL}'")
    s = df[TIME_COL].astype(str).str.replace("_", " ", regex=False)
    return pd.to_datetime(s, errors="coerce")


def load_experiments(experiments: Dict[str, str]) -> pd.DataFrame:
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

    if TEMP_COL not in data.columns:
        raise ValueError(f"Missing temperature column '{TEMP_COL}'. Available: {list(data.columns)}")

    return data


def prepare_data(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy()

    df = df.dropna(subset=["seconds", TEMP_COL])
    df = df.sort_values(["condition", "seconds"])

    if TRIM_SECONDS > 0:
        df = df[df["seconds"] >= TRIM_SECONDS]

    # smoothing
    if SMOOTH_MEDIAN_WINDOW <= 1:
        df["temp_used"] = df[TEMP_COL]
    else:
        df["temp_used"] = (
            df.groupby("condition")[TEMP_COL]
              .transform(lambda s: s.rolling(window=SMOOTH_MEDIAN_WINDOW, center=True).median())
        )

    # time bins
    df["tbin"] = (df["seconds"] // BIN_SECONDS) * BIN_SECONDS
    return df


# =========================
# METRICS
# =========================

def compute_plateau(df: pd.DataFrame) -> pd.DataFrame:
    end_sec = df.groupby("condition")["seconds"].transform("max")
    return df[df["seconds"] >= (end_sec - PLATEAU_LAST_S)]


def summary_table(df: pd.DataFrame) -> pd.DataFrame:
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
    rows = []
    for cond, g in df.groupby("condition"):
        hit = g[g["temp_used"] >= THRESHOLD_C]
        t = float(hit["seconds"].min()) if not hit.empty else np.nan
        rows.append({"condition": cond, f"time_to_{THRESHOLD_C}C_s": t})
    return pd.DataFrame(rows).sort_values(f"time_to_{THRESHOLD_C}C_s")


def correlation_table(df: pd.DataFrame) -> pd.DataFrame:
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
# PLOTS (return base64)
# =========================

def plot_line_temp(df: pd.DataFrame) -> str:
    fig, ax = plt.subplots(figsize=(12, 4))
    for cond, g in df.groupby("condition"):
        g = g.sort_values("seconds")
        ax.plot(g["seconds"], g["temp_used"], label=cond)
    ax.set_title(f"Temp over time (trim={TRIM_SECONDS}s, median_window={SMOOTH_MEDIAN_WINDOW})")
    ax.set_xlabel("seconds")
    ax.set_ylabel("Temp (°C)")
    ax.legend()
    return fig_to_base64_png(fig)


def plot_heatmap(df: pd.DataFrame) -> str:
    pivot = (
        df.pivot_table(index="condition", columns="tbin", values="temp_used", aggfunc="median")
          .sort_index()
          .sort_index(axis=1)
    )

    fig, ax = plt.subplots(figsize=(12, 3))
    im = ax.imshow(pivot.values, aspect="auto")
    ax.set_title(f"Heatmap: median temp (bin={BIN_SECONDS}s)")
    ax.set_ylabel("condition")
    ax.set_xlabel("time bin (seconds)")

    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)

    step = max(1, pivot.shape[1] // 10)
    xticks = list(range(0, pivot.shape[1], step))
    ax.set_xticks(xticks)
    ax.set_xticklabels([str(int(pivot.columns[i])) for i in xticks])

    fig.colorbar(im, ax=ax, label="°C")
    return fig_to_base64_png(fig)


def plot_delta_heatmap(df: pd.DataFrame) -> str | None:
    if BASELINE not in df["condition"].unique():
        return None

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
    return fig_to_base64_png(fig)


def plot_time_to_threshold_bar(t2t: pd.DataFrame) -> str:
    col = f"time_to_{THRESHOLD_C}C_s"
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.bar(t2t["condition"].astype(str), t2t[col])
    ax.set_title(f"Time to reach {THRESHOLD_C}°C (temp_used)")
    ax.set_xlabel("condition")
    ax.set_ylabel("seconds")
    return fig_to_base64_png(fig)


# =========================
# HTML BUILD
# =========================

def df_to_html_table(df: pd.DataFrame, float_fmt: str = "{:.3f}") -> str:
    """
    Lightweight HTML table with some formatting.
    """
    df2 = df.copy()
    for c in df2.columns:
        if pd.api.types.is_float_dtype(df2[c]):
            df2[c] = df2[c].map(lambda x: "" if pd.isna(x) else float_fmt.format(x))
    return df2.to_html(index=False, escape=True)


def build_html(report_title: str,
               config_lines: List[str],
               tables: Dict[str, pd.DataFrame],
               images: Dict[str, str]) -> str:
    style = """
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }
      h1 { margin-bottom: 0.2rem; }
      .muted { color: #555; margin-top: 0; }
      .block { margin: 18px 0 26px 0; }
      .img { border: 1px solid #ddd; border-radius: 8px; padding: 8px; background: #fafafa; }
      table { border-collapse: collapse; margin-top: 10px; }
      th, td { border: 1px solid #ddd; padding: 6px 8px; font-size: 13px; }
      th { background: #f3f3f3; }
      code { background: #f3f3f3; padding: 2px 5px; border-radius: 4px; }
      ul { margin-top: 8px; }
    </style>
    """

    cfg_html = "<ul>" + "".join(f"<li><code>{html.escape(line)}</code></li>" for line in config_lines) + "</ul>"

    parts = [f"<!doctype html><html><head><meta charset='utf-8'>{style}<title>{html.escape(report_title)}</title></head><body>"]
    parts.append(f"<h1>{html.escape(report_title)}</h1>")
    parts.append("<p class='muted'>Auto-generated report (single HTML). Open in any browser.</p>")

    parts.append("<div class='block'><h2>Config</h2>" + cfg_html + "</div>")

    parts.append("<div class='block'><h2>Tables</h2>")
    for name, df in tables.items():
        parts.append(f"<h3>{html.escape(name)}</h3>")
        parts.append(df_to_html_table(df))
    parts.append("</div>")

    parts.append("<div class='block'><h2>Plots</h2>")
    for name, b64png in images.items():
        parts.append(f"<h3>{html.escape(name)}</h3>")
        parts.append(f"<div class='img'><img style='max-width: 100%; height: auto;' src='data:image/png;base64,{b64png}'></div>")
    parts.append("</div>")

    parts.append("</body></html>")
    return "\n".join(parts)


# =========================
# MAIN
# =========================

def main() -> None:
    raw = load_experiments(EXPERIMENTS)
    df = prepare_data(raw)

    # metrics
    summary = summary_table(df)
    t2t = time_to_threshold(df)
    corr = correlation_table(df)

    # save tables as CSV too (handy for PBI)
    summary.to_csv(OUT_DIR / "summary_plateau.csv", index=False)
    t2t.to_csv(OUT_DIR / "time_to_threshold.csv", index=False)
    corr.to_csv(OUT_DIR / "correlations.csv", index=False)

    # plots -> base64
    images: Dict[str, str] = {}
    images["Line: temp over time (smoothed)"] = plot_line_temp(df)
    images["Heatmap: median temp over time"] = plot_heatmap(df)

    delta_b64 = plot_delta_heatmap(df)
    if delta_b64 is not None:
        images[f"Delta heatmap vs baseline ({BASELINE})"] = delta_b64

    images[f"Time-to-threshold ({THRESHOLD_C}°C)"] = plot_time_to_threshold_bar(t2t)

    # HTML
    title = "Thermal Lab Report — cooling experiments"
    cfg_lines = [
        f"EXPERIMENTS = {list(EXPERIMENTS.keys())}",
        f"TEMP_COL = {TEMP_COL}",
        f"BASELINE = {BASELINE}",
        f"TRIM_SECONDS = {TRIM_SECONDS}",
        f"SMOOTH_MEDIAN_WINDOW = {SMOOTH_MEDIAN_WINDOW}",
        f"BIN_SECONDS = {BIN_SECONDS}",
        f"PLATEAU_LAST_S = {PLATEAU_LAST_S}",
        f"THRESHOLD_C = {THRESHOLD_C}",
    ]

    tables = {
        "Summary (plateau stats on temp_used)": summary,
        f"Time-to-threshold (first temp_used ≥ {THRESHOLD_C}°C)": t2t,
        "Correlations (Pearson vs Spearman)": corr,
    }

    html_text = build_html(title, cfg_lines, tables, images)
    REPORT_PATH.write_text(html_text, encoding="utf-8")

    print("Done.")
    print("Report:", REPORT_PATH.resolve())
    print("Tables:", OUT_DIR.resolve())


if __name__ == "__main__":
    main()