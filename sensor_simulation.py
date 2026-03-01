"""
Mine Sensor Simulation
======================
Monitors 6 sensor channels:
  Atmospheric : CH4 (Methane), CO (Carbon Monoxide), H2S (Hydrogen Sulphide),
                CO2 (Carbon Dioxide), O2 (Oxygen depletion)
  Structural  : Seismic Vibration (Richter scale)

Occasional danger spikes simulate hazardous underground conditions.
"""

import random
import time
import datetime

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

SPIKE_PROBABILITY = 0.15  
INTERVAL_SECONDS  = 3


# ── Thresholds (industry-standard mining limits) ──────────────────────────────
#    O2 and seismic use inverted logic: danger = value drops (O2) or rises (seismic)
THRESHOLDS = {
    "ch4":     {"warning": 1.0,   "danger": 2.5},   # % vol  (LEL = 5%)
    "co":      {"warning": 25,    "danger": 100},    # PPM    (TWA=25, IDLH=1200)
    "h2s":     {"warning": 1,     "danger": 10},     # PPM    (TWA=1,  IDLH=50)
    "co2":     {"warning": 0.5,   "danger": 1.5},    # % vol
    "o2":      {"warning": 19.5,  "danger": 16.0},   # % vol  (normal ~20.9%)
    "seismic": {"warning": 2.0,   "danger": 3.5},    # Richter
}

# ── Normal operating ranges ───────────────────────────────────────────────────
NORMAL = {
    "ch4":     (0.0,  0.5),
    "co":      (0,    15),
    "h2s":     (0.0,  0.5),
    "co2":     (0.03, 0.4),
    "o2":      (20.0, 20.9),
    "seismic": (0.0,  1.2),
}

# ── Spike ranges (danger events) ──────────────────────────────────────────────
SPIKES = {
    "ch4":     (2.0,  4.5),
    "co":      (80,   300),
    "h2s":     (8,    50),
    "co2":     (1.2,  3.0),
    "o2":      (13.0, 18.5),   # O2 drops during a spike
    "seismic": (3.0,  5.0),
}

# ── Display metadata ──────────────────────────────────────────────────────────
META = {
    "ch4":     {"label": "Methane         (CH4)", "unit": "% vol",  "group": "GAS"},
    "co":      {"label": "Carbon Monoxide  (CO)", "unit": "PPM",    "group": "GAS"},
    "h2s":     {"label": "Hydrogen Sulphide  (H2S)", "unit": "PPM",    "group": "GAS"},
    "co2":     {"label": "Carbon Dioxide  (CO2)", "unit": "% vol",  "group": "GAS"},
    "o2":      {"label": "Oxygen           (O2)", "unit": "% vol",  "group": "GAS"},
    "seismic": {"label": "Seismic Vibration    ", "unit": "Richter","group": "STRUCTURAL"},
}

# Sensor ordering for display
SENSOR_ORDER = ["ch4", "co", "h2s", "co2", "o2", "seismic"]


# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_status(sensor, value):
    """Return (label, severity) where severity: 0=ok, 1=warning, 2=danger."""
    t = THRESHOLDS[sensor]
    if sensor == "o2":
        if value <= t["danger"]:  return ("DANGER  [!!!]", 2)
        if value <= t["warning"]: return ("WARNING [ ! ]", 1)
        return ("OK      [   ]", 0)
    else:
        if value >= t["danger"]:  return ("DANGER  [!!!]", 2)
        if value >= t["warning"]: return ("WARNING [ ! ]", 1)
        return ("OK      [   ]", 0)


def is_dangerous(sensor, value):
    _, sev = get_status(sensor, value)
    return sev == 2


def is_warning(sensor, value):
    _, sev = get_status(sensor, value)
    return sev == 1


def read_sensor(name):
    """Return (value, is_spike)."""
    spiking = random.random() < SPIKE_PROBABILITY
    lo, hi  = SPIKES[name] if spiking else NORMAL[name]
    value   = round(random.uniform(lo, hi), 3)
    return value, spiking


def format_row(sensor, value, spiking):
    meta        = META[sensor]
    stat_label, _ = get_status(sensor, value)
    spike       = "  <- SPIKE DETECTED" if spiking else ""
    return (
        f"  {meta['label']:<28}  "
        f"{value:>9.3f} {meta['unit']:<8} "
        f"[{stat_label}]{spike}"
    )


def sep(char="─", width=78):
    return char * width


# ─────────────────────────────────────────────────────────────────────────────
#  THRESHOLD LEGEND (printed once at startup)
# ─────────────────────────────────────────────────────────────────────────────

def print_legend():
    print(sep("="))
    print("  SENSOR THRESHOLDS  (Industry Standard / Mining Regulations)")
    print(sep())
    rows = [
        ("Methane (CH4)",           "Gas",        ">= 1.0 % vol",   ">= 2.5 % vol",   "LEL = 5% vol  --  explosive risk"),
        ("Carbon Monoxide (CO)",     "Gas",        ">= 25 PPM",      ">= 100 PPM",      "IDLH = 1200 PPM"),
        ("Hydrogen Sulphide (H2S)",  "Gas",        ">= 1 PPM",       ">= 10 PPM",       "IDLH = 50 PPM  --  rotten egg gas"),
        ("Carbon Dioxide (CO2)",     "Gas",        ">= 0.5 % vol",   ">= 1.5 % vol",    "Displaces oxygen in low areas"),
        ("Oxygen (O2)",              "Gas",        "<= 19.5 % vol",  "<= 16.0 % vol",   "Normal = 20.9%  --  depletion risk"),
        ("Seismic Vibration",        "Structural", ">= 2.0 Richter", ">= 3.5 Richter",  "Risk of roof collapse / rockburst"),
    ]
    print(f"  {'Sensor':<28} {'Type':<12} {'Warning':>16}  {'Danger':>16}   Notes")
    print(sep())
    for name, typ, warn, danger, note in rows:
        print(f"  {name:<28} {typ:<12} {warn:>16}  {danger:>16}   {note}")
    print(sep("="))
    print()


# ─────────────────────────────────────────────────────────────────────────────
#  CONTEXTUAL ADVISORIES
# ─────────────────────────────────────────────────────────────────────────────

def build_advisories(values):
    adv = []

    # O2 depletion
    o2 = values["o2"]
    if o2 <= 16.0:
        adv.append(f"  [O2  ] CRITICAL DEPLETION ({o2:.3f}% vol) -- SCBA / breathing apparatus required immediately!")
    elif o2 <= 19.5:
        adv.append(f"  [O2  ] Below safe level ({o2:.3f}% vol) -- Monitor closely. Prepare escape sets.")

    # H2S olfactory fatigue
    if values["h2s"] >= 10:
        adv.append(f"  [H2S ] {values['h2s']:.3f} PPM -- Olfactory fatigue risk! Do NOT rely on smell to detect gas.")

    # CH4 explosion risk
    if values["ch4"] >= 2.5:
        adv.append(f"  [CH4 ] {values['ch4']:.3f}% vol -- Approaching explosive range (LEL 5%). Eliminate all ignition sources!")

    # CO incapacitation
    if values["co"] >= 100:
        adv.append(f"  [CO  ] {values['co']:.3f} PPM -- Rapid incapacitation risk. Don CO self-rescuer immediately!")

    # CO2 oxygen displacement
    if values["co2"] >= 1.5:
        adv.append(f"  [CO2 ] {values['co2']:.3f}% vol -- High CO2 may displace O2 in low-lying areas. Check ventilation.")

    # Seismic structural risk
    seis = values["seismic"]
    if seis >= 3.5:
        adv.append(f"  [SEIS] {seis:.3f} Richter -- SEVERE: Risk of roof collapse or rockburst! Evacuate affected headings.")
    elif seis >= 2.0:
        adv.append(f"  [SEIS] {seis:.3f} Richter -- Ground movement detected. Inspect roof supports and pillar integrity.")

    return adv


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    reading_number = 0

    print(sep("="))
    print("  MINE ENVIRONMENTAL & STRUCTURAL MONITORING SYSTEM  --  Live Readings")
    print(sep("="))
    print("  Channels  : CH4 | CO | H2S | CO2 | O2 depletion | Seismic vibration")
    print(f"  Interval  : {INTERVAL_SECONDS}s   |   Spike probability : {int(SPIKE_PROBABILITY * 100)}% per sensor per cycle")
    print(sep())
    print("  Press Ctrl+C to stop.\n")
    print_legend()

    try:
        while True:
            reading_number += 1
            now = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")

            readings = {s: read_sensor(s) for s in SENSOR_ORDER}
            values   = {s: v for s, (v, _) in readings.items()}

            danger_list  = [s for s in SENSOR_ORDER if is_dangerous(s, values[s])]
            warning_list = [s for s in SENSOR_ORDER if is_warning(s, values[s]) and s not in danger_list]

            if danger_list:
                headline = f"*** CRITICAL ALERT -- EVACUATE  ({', '.join(d.upper() for d in danger_list)}) ***"
            elif warning_list:
                headline = f"!! ELEVATED ALERT  ({', '.join(w.upper() for w in warning_list)})"
            else:
                headline = "ALL SENSORS NORMAL"

            # ── Header ──────────────────────────────────────────────────────
            print(sep())
            print(f"  Reading #{reading_number:<5}  {now}")
            print(f"  Status  : {headline}")
            print(sep())

            # ── Gas sensors ─────────────────────────────────────────────────
            print("  [ ATMOSPHERIC ]")
            for s in ["ch4", "co", "h2s", "co2", "o2"]:
                v, spike = readings[s]
                print(format_row(s, v, spike))

            print()

            # ── Structural sensor ────────────────────────────────────────────
            print("  [ STRUCTURAL ]")
            v, spike = readings["seismic"]
            print(format_row("seismic", v, spike))

            print(sep())
            print()
            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print(sep("="))
        print(f"  Monitoring stopped after {reading_number} reading(s). Stay safe underground!")
        print(sep("="))


if __name__ == "__main__":
    main()









