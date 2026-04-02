"""
MineGuard — Realistic Sensor Simulation with MQTT Publishing
=============================================================
Improvements over basic version:
  - Smooth continuous sensor behavior (no random jumps)
  - Noise + drift + inertia
  - Gradual spike buildup and decay
  - Spike persistence (multi-cycle events)
  - Inter-sensor correlation (O2 affected by gases)
  - MQTT publishing to mineguard/sensors/#

Run AFTER starting broker:  mosquitto -v
"""

import random
import time
import datetime
import json
import sys

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    print("[WARN] paho-mqtt not installed. Running in PRINT-ONLY mode.")
    print("       Install:  pip install paho-mqtt --break-system-packages\n")

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

MQTT_BROKER       = "localhost"
MQTT_PORT         = 1883
INTERVAL_SECONDS  = 3
ZONE              = "Zone-A"
NODE_ID           = "NODE-01"

SPIKE_PROBABILITY = 0.03   # 3% per sensor per cycle — realistic
ALPHA             = 0.2    # smoothing / inertia factor

THRESHOLDS = {
    "ch4":     {"warning": 1.0,   "danger": 2.5},
    "co":      {"warning": 25,    "danger": 100},
    "h2s":     {"warning": 1,     "danger": 10},
    "co2":     {"warning": 0.5,   "danger": 1.5},
    "o2":      {"warning": 19.5,  "danger": 16.0},
    "seismic": {"warning": 2.0,   "danger": 3.5},
}

NORMAL = {
    "ch4":     (0.0,  0.5),
    "co":      (0,    15),
    "h2s":     (0.0,  0.5),
    "co2":     (0.03, 0.4),
    "o2":      (20.0, 20.9),
    "seismic": (0.0,  1.2),
}

SPIKES = {
    "ch4":     (2.0,  4.5),
    "co":      (80,   300),
    "h2s":     (8,    50),
    "co2":     (1.2,  3.0),
    "o2":      (13.0, 18.5),
    "seismic": (3.0,  5.0),
}

META = {
    "ch4":     {"label": "Methane         (CH4)", "unit": "% vol",  "group": "GAS"},
    "co":      {"label": "Carbon Monoxide  (CO)", "unit": "PPM",    "group": "GAS"},
    "h2s":     {"label": "Hydrogen Sulphide(H2S)","unit": "PPM",    "group": "GAS"},
    "co2":     {"label": "Carbon Dioxide  (CO2)", "unit": "% vol",  "group": "GAS"},
    "o2":      {"label": "Oxygen           (O2)", "unit": "% vol",  "group": "GAS"},
    "seismic": {"label": "Seismic Vibration    ", "unit": "Richter","group": "STRUCTURAL"},
}

SENSOR_ORDER = ["ch4", "co", "h2s", "co2", "o2", "seismic"]

# ─────────────────────────────────────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────────────────────────────────────

STATE       = {s: sum(NORMAL[s]) / 2 for s in SENSOR_ORDER}
SPIKE_STATE = {s: 0 for s in SENSOR_ORDER}

# ─────────────────────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_status(sensor, value):
    t = THRESHOLDS[sensor]
    if sensor == "o2":
        if value <= t["danger"]:  return ("DANGER  [!!!]", 2)
        if value <= t["warning"]: return ("WARNING [ ! ]", 1)
        return ("OK      [   ]", 0)
    else:
        if value >= t["danger"]:  return ("DANGER  [!!!]", 2)
        if value >= t["warning"]: return ("WARNING [ ! ]", 1)
        return ("OK      [   ]", 0)

def is_dangerous(sensor, value): return get_status(sensor, value)[1] == 2
def is_warning(sensor, value):   return get_status(sensor, value)[1] == 1

def get_level_str(sensor, value):
    _, sev = get_status(sensor, value)
    return "DANGER" if sev == 2 else "WARNING" if sev == 1 else "SAFE"

# ─────────────────────────────────────────────────────────────────────────────
#  REALISTIC SENSOR MODEL
# ─────────────────────────────────────────────────────────────────────────────

def read_sensor(name):
    prev  = STATE[name]
    noise = random.uniform(-0.02, 0.02)
    drift = random.uniform(-0.01, 0.01)

    if SPIKE_STATE[name] > 0:
        SPIKE_STATE[name] -= 1
        spike_target = random.uniform(*SPIKES[name])
        change  = (spike_target - prev) * 0.2
        spiking = True
    elif random.random() < SPIKE_PROBABILITY:
        SPIKE_STATE[name] = random.randint(3, 8)
        spike_target = random.uniform(*SPIKES[name])
        change  = (spike_target - prev) * 0.2
        spiking = True
    else:
        normal_mid = sum(NORMAL[name]) / 2
        change  = (normal_mid - prev) * 0.05
        spiking = False

    new_value = prev + noise + drift + change
    new_value = ALPHA * new_value + (1 - ALPHA) * prev
    lo, hi    = SPIKES[name]
    new_value = max(min(new_value, hi), lo)
    STATE[name] = round(new_value, 3)
    return STATE[name], spiking

# ─────────────────────────────────────────────────────────────────────────────
#  CORRELATION
# ─────────────────────────────────────────────────────────────────────────────

def apply_correlation(values):
    values["o2"] -= values["co2"] * 0.001
    values["o2"] -= values["ch4"] * 0.002
    values["o2"]  = round(max(13.0, min(20.9, values["o2"])), 3)
    return values

# ─────────────────────────────────────────────────────────────────────────────
#  ADVISORY BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_advisories(values):
    adv = []
    o2  = values.get("o2", 20.9)
    if o2 <= 16.0:
        adv.append(f"CRITICAL O2 DEPLETION ({o2:.3f}%) — SCBA required immediately!")
    elif o2 <= 19.5:
        adv.append(f"O2 below safe level ({o2:.3f}%) — Monitor closely.")
    if values.get("h2s", 0) >= 10:
        adv.append(f"H2S {values['h2s']:.3f} PPM — Olfactory fatigue risk!")
    if values.get("ch4", 0) >= 2.5:
        adv.append(f"CH4 {values['ch4']:.3f}% — Approaching explosive range!")
    if values.get("co", 0) >= 100:
        adv.append(f"CO {values['co']:.3f} PPM — Rapid incapacitation risk!")
    if values.get("co2", 0) >= 1.5:
        adv.append(f"CO2 {values['co2']:.3f}% — May displace O2. Increase ventilation.")
    seis = values.get("seismic", 0)
    if seis >= 3.5:
        adv.append(f"SEISMIC {seis:.3f} Richter — SEVERE: Risk of roof collapse!")
    elif seis >= 2.0:
        adv.append(f"SEISMIC {seis:.3f} Richter — Ground movement. Inspect roof supports.")
    return adv

# ─────────────────────────────────────────────────────────────────────────────
#  DISPLAY
# ─────────────────────────────────────────────────────────────────────────────

def format_row(sensor, value, spiking):
    meta          = META[sensor]
    stat_label, _ = get_status(sensor, value)
    spike         = "  <- SPIKE" if spiking else ""
    return (
        f"  {meta['label']:<28} "
        f"{value:>9.3f} {meta['unit']:<8} "
        f"[{stat_label}]{spike}"
    )

def sep(char="─", w=78):
    return char * w

# ─────────────────────────────────────────────────────────────────────────────
#  MQTT
# ─────────────────────────────────────────────────────────────────────────────

mqtt_client    = None
mqtt_connected = False

def on_mqtt_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        print(f"[MQTT] Connected to broker {MQTT_BROKER}:{MQTT_PORT}")
    else:
        print(f"[MQTT] Connection failed rc={rc}")

def on_mqtt_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    print(f"[MQTT] Disconnected (rc={rc}) — will reconnect automatically")

def setup_mqtt():
    global mqtt_client
    if not MQTT_AVAILABLE:
        return False
    try:
        mqtt_client = mqtt.Client(client_id="mineguard-realistic-sim")
        mqtt_client.on_connect    = on_mqtt_connect
        mqtt_client.on_disconnect = on_mqtt_disconnect
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
        time.sleep(0.8)
        return True
    except Exception as e:
        print(f"[MQTT] Cannot connect: {e} — print-only mode")
        return False

def publish_readings(values, spikes, reading_number):
    if not mqtt_connected or not mqtt_client:
        return

    ts = datetime.datetime.utcnow().isoformat()

    # Individual sensor topics
    for sensor in SENSOR_ORDER:
        value   = values[sensor]
        spiking = spikes.get(sensor, False)
        payload = {
            "sensor":     sensor,
            "value":      value,
            "unit":       META[sensor]["unit"],
            "group":      META[sensor]["group"],
            "level":      get_level_str(sensor, value),
            "is_spike":   spiking,
            "timestamp":  ts,
            "reading_id": reading_number,
            "zone":       ZONE,
            "node_id":    NODE_ID,
        }
        mqtt_client.publish(f"mineguard/sensors/{sensor}", json.dumps(payload), qos=1)

    # Combined snapshot
    danger_sensors  = [s for s in SENSOR_ORDER if is_dangerous(s, values[s])]
    warning_sensors = [s for s in SENSOR_ORDER if is_warning(s, values[s])]
    overall_status  = "DANGER" if danger_sensors else "WARNING" if warning_sensors else "SAFE"

    combined = {
        "timestamp":      ts,
        "reading_id":     reading_number,
        "zone":           ZONE,
        "node_id":        NODE_ID,
        "overall_status": overall_status,
        "readings":       values,
        "spikes":         {s: spikes.get(s, False) for s in SENSOR_ORDER},
        "advisories":     build_advisories(values),
    }
    mqtt_client.publish("mineguard/sensors/all", json.dumps(combined), qos=1)
    print(f"  [MQTT] Published #{reading_number} → broker  (status: {overall_status})")

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    reading_number = 0
    mqtt_ok        = setup_mqtt()

    print(sep("="))
    print("  MINEGUARD — REALISTIC SENSOR SIMULATION")
    print(sep("="))
    print("  Smooth signals | Drift | Persistent spikes | Correlated gases")
    print(f"  MQTT broker : {MQTT_BROKER}:{MQTT_PORT}  (connected={mqtt_ok})")
    print(f"  Zone        : {ZONE}  |  Node: {NODE_ID}")
    print(f"  Interval    : {INTERVAL_SECONDS}s  |  Spike probability: {int(SPIKE_PROBABILITY*100)}% per sensor")
    print(sep())
    print("  Press Ctrl+C to stop.\n")

    try:
        while True:
            reading_number += 1
            now          = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            raw_readings = {s: read_sensor(s) for s in SENSOR_ORDER}
            values       = {s: v  for s, (v, _)  in raw_readings.items()}
            spikes       = {s: sp for s, (_, sp) in raw_readings.items()}
            values       = apply_correlation(values)

            danger_list  = [s for s in SENSOR_ORDER if is_dangerous(s, values[s])]
            warning_list = [s for s in SENSOR_ORDER if is_warning(s, values[s]) and s not in danger_list]

            if danger_list:
                headline = f"*** CRITICAL ({', '.join(d.upper() for d in danger_list)}) ***"
            elif warning_list:
                headline = f"!! WARNING ({', '.join(w.upper() for w in warning_list)})"
            else:
                headline = "ALL NORMAL"

            print(sep())
            print(f"  Reading #{reading_number:<5}  {now}")
            print(f"  Status  : {headline}")
            print(sep())
            print("  [ ATMOSPHERIC ]")
            for s in ["ch4", "co", "h2s", "co2", "o2"]:
                print(format_row(s, values[s], spikes[s]))
            print()
            print("  [ STRUCTURAL ]")
            print(format_row("seismic", values["seismic"], spikes["seismic"]))
            print(sep())

            publish_readings(values, spikes, reading_number)
            print()
            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print(sep("="))
        print(f"  Simulation stopped after {reading_number} reading(s). Stay safe underground!")
        print(sep("="))
        if mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()

if __name__ == "__main__":
    main()
