# HTherMaL-laptop-cooling-bench

CPU cooling research on legacy hardware: s-tui telemetry, pandas analysis, heatmaps & interactive HTML dashboards. 10 airflow configs, 2 study phases, reproducible pipeline. Findings documented in full report.

---

<img width="1897" height="1078" alt="image" src="https://github.com/user-attachments/assets/ba04cc9c-16cb-4b11-848a-69865fbec139" />

---

## Background

Clevo W650SR on Linux Mint 22.2 — all upgradeable hardware components already replaced or maxed out. Heavy browser workloads still caused OOM kills and system freezes. The main driver: CPU running at turbo frequencies under sustained load, pushing past the thermal limit, which triggered throttling and instability. With no hardware options left, the question was whether airflow geometry alone could produce a measurable improvement.

This repository documents a structured two-phase study that found a reproducible fix — CPU temperatures dropped, OOM kills stopped, and the laptop runs stable under workloads that previously caused crashes.

---

## Hardware

| | |
|--|--|
| Model | Clevo W650SR |
| CPU | Intel Core i7-4700MQ (4C/8T, 45W TDP) |
| GPU | NVIDIA GeForce GT 750M |
| Cooling | Shared CPU/GPU heatpipe, single fan |
| OS | Linux Mint 22.2 |

The shared heatpipe means CPU and GPU compete for the same thermal budget. Display heat also feeds into the same system — relevant to the screen-state tests in Study II.

---

## Instrumentation

**s-tui** with the built-in `--csv` flag for telemetry logging:

```bash
s-tui --csv-file 20260227_fan_5min.csv
```

Without the flag, s-tui is real-time display only — no data saved. Each test: 5 minutes, 100% CPU stress, ~2s sampling. Columns recorded: timestamp, CPU package temp, per-core temps, average frequency, average utilisation.

Analysis stack: **Python · pandas · numpy · matplotlib**

---

## Study I — Three baseline conditions

→ *[Full Phase 1 report](phase1/REPORT.md)*

| Condition | Plateau mean | Max | Time to 90°C |
|-----------|-------------|-----|-------------|
| desk | 92.77°C | 94°C | 34s |
| fan | 91.38°C | 93°C | 55s |
| **raised** | **90.70°C** | **93°C** | **80s** |

`raised` beat `fan`. A large undirected fan recirculates warm air rather than evacuating it. This result produced the core hypothesis for Study II: **airflow direction matters more than airflow volume.**

**Key visual:** the delta heatmap (each condition minus `raised` baseline, 5s bins) was the clearest result of Study I. `raised` showed the flattest, most consistent thermal profile across the full 5-minute test — not just a lower average, but lower oscillation throughout. `desk` ran +2–4°C above baseline from the first minute onward, without recovery.

The analysis pipeline was built and refined across this phase — details in the Phase 1 report.

---

## Study II — 10 conditions, precision mini-fan

A small USB fan on a flexible neck, tested in five different positions, plus screen-state conditions added to the three Study I configs.

### Full ranking — plateau mean temperature (last 60s)

| # | Condition | Plateau °C | Max °C | p95 °C | Time to 90°C |
|---|-----------|-----------|--------|--------|-------------|
| 1 | mini-fan · lazy placement | 90.10 | **92** | **91** | 93s |
| 2 | mini-fan · parallel to north | 90.55 | **92** | **91** | 92s |
| 3 | raised *(Study I)* | 90.58 | 93 | 92 | 72s |
| 4 | **mini-fan · near radiator** | **90.61** | **92** | **91** | **73s** |
| 5 | mini-fan · to center | 91.00 | 93 | 92 | 32s |
| 6 | open screen off | 91.20 | 93 | 92 | 63s |
| 7 | fan *(Study I)* | 91.37 | 93 | 92 | 55s |
| 8 | open screen on | 91.83 | 93 | 93 | 45s |
| 9 | after start closed | 92.13 | 94 | 93 | 75s |
| 10 | desk *(Study I)* | 92.42 | 94 | 94 | 34s |

### Why near-radiator is the winner

By plateau mean, `lazy` appears first (90.10°C vs 90.61°C). Two reasons this does not hold up.

**Measurement resolution.** Telemetry records in 1°C integers. CPU oscillates between 90 and 91°C at plateau. A 0.51°C mean difference across 30 readings is ~15 readings at 91 vs 90 — within the quantisation range, not a real thermal gap.

**Peak behaviour.** Scoring by `max_C` and `p95_C` — the values that drive throttling risk:

| Condition | max_C | p95_C | Peak score |
|-----------|-------|-------|-----------|
| mini-fan · lazy | 92 | 91 | **1.000** |
| mini-fan · parallel to north | 92 | 91 | **1.000** |
| **mini-fan · near radiator** | **92** | **91** | **1.000** |
| raised | 93 | 92 | 0.567 |
| desk | 94 | 94 | 0.000 |

All three top configs share the same 92°C peak ceiling. Near-radiator ties for first on the metric that matters.

**Tiebreaker: reproducibility and mechanism.** `Lazy` is an uncontrolled position — it worked in one test but cannot be reliably repeated. `Near radiator` aims directly at the CPU exhaust vent: hot air is removed at the source before it can recirculate. The only placement with a clear physical reason to work. Real-world use confirmed it as the consistent choice.

### Open lid nuance

`open_screen_on` vs `open_screen_off`: **+0.63°C** on plateau. The active display adds load through the shared heatpipe. Small but reproducible.

### Interactive dashboard

`phase2/results/thermal_v4.html` — open locally in any browser.

> Built as an interactive HTML artifact with **Claude Sonnet 4.6**.

---

## Optimal configuration

| Improvement | Δ plateau vs desk |
|-------------|-----------------|
| Raise the laptop | −1.84°C |
| Mini-fan at radiator exhaust | −1.81°C |
| Open lid, screen off | −0.63°C |

**Best setup: laptop raised + lid open + small USB fan aimed at the exhaust vent.**
Combined estimate: ~−2.4°C on plateau, 92°C peak vs 94°C for desk.

---

## Key findings

- Large fan ranked 7th out of 10. Volume without direction is mostly wasted.
- `mini-fan to-center` is the worst mini-fan placement: 32s to 90°C, nearly as fast as desk (34s). Airflow with no exit path adds turbulence, not cooling.
- `after_start_closed`: running a test on an already-warm laptop scores second-worst. Thermal starting state matters more than expected.
- Frequency throttling was not observed across any condition — CPU held ~3193 MHz throughout. Temperature affects stability through OOM/freeze paths, not clock reduction.

---

## Result

After switching to the optimal configuration: OOM kills stopped, no further freezes under heavy browser workloads, CPU frequency behaviour more stable. A 2°C drop in sustained plateau and a 2°C reduction in peak temperature shifted the system out of the instability zone.

---

## Repository structure

```
TODO
```

---

## Run

```bash
pip install pandas numpy matplotlib

cd phase1/src
python HTherMaL_lab_report.py    # → ../results/thermal_report.html
```

Experiment config: edit the `EXPERIMENTS` dict at the top of the script.

---

*HTherMaL · Clevo W650SR · i7-4700MQ · Linux Mint 22.2*
