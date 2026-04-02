"""
MineGuard — Training Data Generator (Realistic + Balanced)
============================================================
Generates labelled CSV with 3 classes: safe / warning / danger.
Uses the same sensor model as simulation.py for realism,
but produces a balanced dataset by explicitly generating
safe, warning, and danger scenarios.

Run:  python scripts/generate_training_data.py
"""

import csv
import random
import os

CYCLES   = 10000
OUT_FILE = os.path.join(os.path.dirname(__file__), "..", "models", "training_data.csv")

THRESHOLDS = {
    "ch4":     {"warning": 1.0,   "danger": 2.5},
    "co":      {"warning": 25,    "danger": 100},
    "h2s":     {"warning": 1,     "danger": 10},
    "co2":     {"warning": 0.5,   "danger": 1.5},
    "o2":      {"warning": 19.5,  "danger": 16.0},
    "seismic": {"warning": 2.0,   "danger": 3.5},
}

SENSOR_ORDER = ["ch4", "co", "h2s", "co2", "o2", "seismic"]

# Explicit safe ranges (well inside thresholds)
SAFE_RANGES = {
    "ch4":     (0.01, 0.8),
    "co":      (0.5,  20),
    "h2s":     (0.01, 0.8),
    "co2":     (0.04, 0.45),
    "o2":      (20.0, 20.9),
    "seismic": (0.1,  1.8),
}

# Warning ranges (between warning and danger thresholds)
WARN_RANGES = {
    "ch4":     (1.0,  2.4),
    "co":      (25,   99),
    "h2s":     (1.0,  9.9),
    "co2":     (0.5,  1.4),
    "o2":      (16.1, 19.5),
    "seismic": (2.0,  3.4),
}

# Danger ranges (above danger threshold)
DANGER_RANGES = {
    "ch4":     (2.5,  4.5),
    "co":      (100,  300),
    "h2s":     (10,   50),
    "co2":     (1.5,  3.0),
    "o2":      (13.0, 16.0),
    "seismic": (3.5,  5.0),
}

ALPHA    = 0.2
SPIKE_PROB = 0.03


def apply_correlation(values):
    values["o2"] -= values["co2"] * 0.001
    values["o2"] -= values["ch4"] * 0.002
    values["o2"]  = round(max(13.0, min(20.9, values["o2"])), 4)
    return values


def gen_safe_reading():
    """Generate a reading where all sensors are in safe range."""
    values = {s: round(random.uniform(*SAFE_RANGES[s]), 4) for s in SENSOR_ORDER}
    values = apply_correlation(values)
    return values


def gen_warning_reading():
    """At least one sensor in warning range, none in danger."""
    values = {s: round(random.uniform(*SAFE_RANGES[s]), 4) for s in SENSOR_ORDER}
    # Elevate 1–2 sensors to warning range
    n_warn = random.randint(1, 2)
    sensors_to_warn = random.sample(SENSOR_ORDER, n_warn)
    for s in sensors_to_warn:
        values[s] = round(random.uniform(*WARN_RANGES[s]), 4)
    values = apply_correlation(values)
    return values


def gen_danger_reading():
    """At least one sensor in danger range."""
    values = {s: round(random.uniform(*SAFE_RANGES[s]), 4) for s in SENSOR_ORDER}
    n_danger = random.randint(1, 2)
    sensors_to_spike = random.sample(SENSOR_ORDER, n_danger)
    for s in sensors_to_spike:
        values[s] = round(random.uniform(*DANGER_RANGES[s]), 4)
    values = apply_correlation(values)
    return values


def get_label(values):
    """0=safe, 1=warning, 2=danger"""
    for s in SENSOR_ORDER:
        v = values[s]
        t = THRESHOLDS[s]
        if s == "o2":
            if v <= t["danger"]:  return 2
            if v <= t["warning"]: return 1
        else:
            if v >= t["danger"]:  return 2
            if v >= t["warning"]: return 1
    return 0


def main():
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    rows   = []
    labels = {0: 0, 1: 0, 2: 0}

    # Balanced split: 50% safe, 30% warning, 20% danger
    n_safe    = int(CYCLES * 0.50)
    n_warning = int(CYCLES * 0.30)
    n_danger  = CYCLES - n_safe - n_warning

    print(f"[GEN] Generating {CYCLES} readings: {n_safe} safe / {n_warning} warning / {n_danger} danger ...")

    for _ in range(n_safe):
        v = gen_safe_reading()
        l = get_label(v)
        rows.append({**v, "label": l})
        labels[l] += 1

    for _ in range(n_warning):
        v = gen_warning_reading()
        l = get_label(v)
        rows.append({**v, "label": l})
        labels[l] += 1

    for _ in range(n_danger):
        v = gen_danger_reading()
        l = get_label(v)
        rows.append({**v, "label": l})
        labels[l] += 1

    # Shuffle
    random.shuffle(rows)

    fieldnames = SENSOR_ORDER + ["label"]
    with open(OUT_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    print(f"\n[OK] Generated {total} readings → {OUT_FILE}")
    print(f"     Label 0 (safe)   : {labels[0]}  ({labels[0]/total*100:.1f}%)")
    print(f"     Label 1 (warning): {labels[1]}  ({labels[1]/total*100:.1f}%)")
    print(f"     Label 2 (danger) : {labels[2]}  ({labels[2]/total*100:.1f}%)")


if __name__ == "__main__":
    main()
