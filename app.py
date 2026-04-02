"""
MineGuard — Flask Backend
==========================
Handles:
  - MQTT subscription (receives sensor readings)
  - InfluxDB writes (time-series storage)
  - MongoDB writes  (alerts, predictions, events)
  - Rules engine    (instant threshold checks)
  - AI inference    (every 30s via APScheduler)
  - WebSocket push  (live dashboard updates)
  - REST API        (dashboard initial load)

Start:  python backend/app.py
"""

import os
import sys
import json
import datetime
import threading
import numpy as np
from collections import defaultdict, deque
from pathlib import Path

# ── Flask ─────────────────────────────────────────────────────────────────────
from flask import Flask, jsonify, render_template_string
from flask_socketio import SocketIO
from flask_cors import CORS

# ── MQTT ──────────────────────────────────────────────────────────────────────
import paho.mqtt.client as mqtt

# ── Database ──────────────────────────────────────────────────────────────────
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from pymongo import MongoClient

# ── Scheduler ─────────────────────────────────────────────────────────────────
from apscheduler.schedulers.background import BackgroundScheduler

# ── ML ────────────────────────────────────────────────────────────────────────
import joblib

# =============================================================================
#  CONFIG
# =============================================================================

MQTT_BROKER   = os.getenv("MQTT_BROKER",   "localhost")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "1883"))

INFLUX_URL    = os.getenv("INFLUX_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN",  "mineguard-token")
INFLUX_ORG    = os.getenv("INFLUX_ORG",    "mineguard")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "mineguard")

MONGO_URI     = os.getenv("MONGO_URI",     "mongodb://localhost:27017")
MONGO_DB      = os.getenv("MONGO_DB",      "mineguard")

MODELS_DIR    = Path(__file__).parent.parent / "models"
AI_INTERVAL   = int(os.getenv("AI_INTERVAL", "30"))   # seconds between AI runs
BUFFER_SIZE   = 50                                      # readings per sensor

THRESHOLDS = {
    "ch4":     {"warning": 1.0,   "danger": 2.5},
    "co":      {"warning": 25,    "danger": 100},
    "h2s":     {"warning": 1,     "danger": 10},
    "co2":     {"warning": 0.5,   "danger": 1.5},
    "o2":      {"warning": 19.5,  "danger": 16.0},
    "seismic": {"warning": 2.0,   "danger": 3.5},
}

SENSOR_ORDER = ["ch4", "co", "h2s", "co2", "o2", "seismic"]
UNITS        = {"ch4":"% vol","co":"PPM","h2s":"PPM","co2":"% vol","o2":"% vol","seismic":"Richter"}

# =============================================================================
#  APP SETUP
# =============================================================================

app      = Flask(__name__)
app.config["SECRET_KEY"] = "mineguard-secret"
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# =============================================================================
#  DATABASE CONNECTIONS
# =============================================================================

# InfluxDB
try:
    influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api     = influx_client.write_api(write_options=SYNCHRONOUS)
    query_api     = influx_client.query_api()
    print(f"[InfluxDB] Connected → {INFLUX_URL}")
    INFLUX_OK = True
except Exception as e:
    print(f"[InfluxDB] Not available: {e}")
    INFLUX_OK = False

# MongoDB
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
    mongo_client.server_info()
    db           = mongo_client[MONGO_DB]
    print(f"[MongoDB]  Connected → {MONGO_URI}")
    MONGO_OK = True
except Exception as e:
    print(f"[MongoDB]  Not available: {e}")
    MONGO_OK = False

# =============================================================================
#  STATE (in-memory)
# =============================================================================

sensor_buffers  = defaultdict(lambda: deque(maxlen=BUFFER_SIZE))
latest_readings = {}          # {sensor: value}
latest_risk     = {}          # last AI result
alert_lock      = threading.Lock()
active_alerts   = {}          # {sensor: alert_doc}

# =============================================================================
#  AI MODELS
# =============================================================================

models = {}

def load_models():
    global models
    required = ["isolation_forest.pkl", "risk_classifier.pkl", "risk_scorer.pkl"]
    missing  = [f for f in required if not (MODELS_DIR / f).exists()]
    if missing:
        print(f"[AI] Models not found: {missing}")
        print(f"[AI] Run:  python scripts/train_models.py  to train them first.")
        return False
    try:
        models["iso"]        = joblib.load(MODELS_DIR / "isolation_forest.pkl")
        models["classifier"] = joblib.load(MODELS_DIR / "risk_classifier.pkl")
        models["scorer"]     = joblib.load(MODELS_DIR / "risk_scorer.pkl")
        print("[AI] All models loaded.")
        return True
    except Exception as e:
        print(f"[AI] Failed to load models: {e}")
        return False

MODELS_LOADED = load_models()

# =============================================================================
#  ADVISORY BUILDER
# =============================================================================

def build_advisories(values):
    adv = []
    o2 = values.get("o2", 20.9)
    if o2 <= 16.0:
        adv.append(f"CRITICAL O2 DEPLETION ({o2:.3f}%) — SCBA required immediately. Initiate evacuation.")
    elif o2 <= 19.5:
        adv.append(f"O2 below safe level ({o2:.3f}%) — Monitor closely. Prepare escape sets.")
    if values.get("h2s", 0) >= 10:
        adv.append(f"H2S at {values['h2s']:.3f} PPM — Olfactory fatigue risk. Do NOT rely on smell.")
    if values.get("ch4", 0) >= 2.5:
        adv.append(f"CH4 at {values['ch4']:.3f}% — Approaching explosive range (LEL 5%). Remove ignition sources.")
    if values.get("co", 0) >= 100:
        adv.append(f"CO at {values['co']:.3f} PPM — Rapid incapacitation risk. Don self-rescuer immediately.")
    if values.get("co2", 0) >= 1.5:
        adv.append(f"CO2 at {values['co2']:.3f}% — May displace O2 in low areas. Increase ventilation.")
    seis = values.get("seismic", 0)
    if seis >= 3.5:
        adv.append(f"SEISMIC {seis:.3f} Richter — SEVERE: Risk of roof collapse. Evacuate affected headings.")
    elif seis >= 2.0:
        adv.append(f"SEISMIC {seis:.3f} Richter — Ground movement. Inspect roof supports and pillar integrity.")
    return adv

# =============================================================================
#  RULES ENGINE  (instant, per-reading)
# =============================================================================

def rules_engine(sensor, value):
    t = THRESHOLDS.get(sensor)
    if not t:
        return None

    if sensor == "o2":
        if value <= t["danger"]:
            level = "DANGER"
            msg   = f"O2 critical at {value:.3f}% vol — breathing apparatus required immediately"
        elif value <= t["warning"]:
            level = "WARNING"
            msg   = f"O2 below safe level: {value:.3f}% vol"
        else:
            return None
    else:
        if value >= t["danger"]:
            level = "DANGER"
            msg   = f"{sensor.upper()} at danger level: {value:.3f} {UNITS.get(sensor,'')}"
        elif value >= t["warning"]:
            level = "WARNING"
            msg   = f"{sensor.upper()} elevated: {value:.3f} {UNITS.get(sensor,'')}"
        else:
            # Clear any existing alert for this sensor
            with alert_lock:
                active_alerts.pop(sensor, None)
            return None

    alert = {
        "level":     level,
        "sensor":    sensor,
        "value":     value,
        "message":   msg,
        "timestamp": datetime.datetime.utcnow().isoformat(),
    }

    with alert_lock:
        active_alerts[sensor] = alert

    # Persist to MongoDB
    if MONGO_OK:
        try:
            db.alerts.insert_one({**alert, "_created": datetime.datetime.utcnow()})
        except Exception:
            pass

    return alert

# =============================================================================
#  INFLUXDB WRITE
# =============================================================================

def write_to_influx(sensor, value, zone, node_id, timestamp):
    if not INFLUX_OK:
        return
    try:
        point = (Point("sensor_readings")
                 .tag("sensor",  sensor)
                 .tag("zone",    zone)
                 .tag("node_id", node_id)
                 .field("value", float(value))
                 .time(timestamp))
        write_api.write(bucket=INFLUX_BUCKET, record=point)
    except Exception as e:
        print(f"[InfluxDB] Write error: {e}")

# =============================================================================
#  AI INFERENCE  (runs every AI_INTERVAL seconds)
# =============================================================================

def run_ai_inference():
    if not MODELS_LOADED:
        return
    if any(len(sensor_buffers[s]) < 5 for s in SENSOR_ORDER):
        return   # Not enough data yet

    try:
        # Build feature vector from latest readings
        feature_vec = np.array([[
            list(sensor_buffers[s])[-1] if sensor_buffers[s] else 0.0
            for s in SENSOR_ORDER
        ]])

        # 1. Anomaly detection
        iso_score  = float(models["iso"].decision_function(feature_vec)[0])
        is_anomaly = bool(models["iso"].predict(feature_vec)[0] == -1)

        # 2. Risk classification (0=safe,1=warning,2=danger)
        risk_class      = int(models["classifier"].predict(feature_vec)[0])
        risk_class_prob = models["classifier"].predict_proba(feature_vec)[0].tolist()

        # 3. Risk probability score (0.0–1.0)
        risk_score = float(models["scorer"].predict_proba(feature_vec)[0][1])

        label_map  = {0: "SAFE", 1: "WARNING", 2: "DANGER"}
        risk_level = label_map[risk_class]

        # Override label if probability is very high
        if risk_score >= 0.75:
            risk_level = "DANGER"
        elif risk_score >= 0.45:
            risk_level = "WARNING"

        advisories = build_advisories(latest_readings)

        result = {
            "timestamp":      datetime.datetime.utcnow().isoformat(),
            "risk_score":     round(risk_score, 4),
            "risk_level":     risk_level,
            "risk_class":     risk_class,
            "class_probs":    {
                "safe":    round(risk_class_prob[0], 4),
                "warning": round(risk_class_prob[1], 4) if len(risk_class_prob) > 1 else 0,
                "danger":  round(risk_class_prob[2], 4) if len(risk_class_prob) > 2 else 0,
            },
            "is_anomaly":     is_anomaly,
            "anomaly_score":  round(iso_score, 4),
            "advisories":     advisories,
            "sensor_snapshot": {s: round(latest_readings.get(s, 0), 4) for s in SENSOR_ORDER},
        }

        global latest_risk
        latest_risk = result

        # Persist prediction to MongoDB
        if MONGO_OK:
            try:
                db.predictions.insert_one({**result, "_created": datetime.datetime.utcnow()})
            except Exception:
                pass

        # Push to dashboard
        socketio.emit("ai_update", result)
        print(f"[AI] Risk={risk_level} ({risk_score:.2f})  Anomaly={is_anomaly}  Advisories={len(advisories)}")

    except Exception as e:
        print(f"[AI] Inference error: {e}")

# =============================================================================
#  MQTT HANDLERS
# =============================================================================

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Connected to broker {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe("mineguard/sensors/#")
        print("[MQTT] Subscribed to  mineguard/sensors/#")
    else:
        print(f"[MQTT] Connection failed rc={rc}")


def on_message(client, userdata, msg):
    try:
        data   = json.loads(msg.payload.decode())
        sensor = data.get("sensor")
        value  = data.get("value")

        if sensor not in SENSOR_ORDER or value is None:
            return

        value  = float(value)
        zone   = data.get("zone",    "unknown")
        node   = data.get("node_id", "unknown")
        ts     = data.get("timestamp", datetime.datetime.utcnow().isoformat())

        # Update state
        sensor_buffers[sensor].append(value)
        latest_readings[sensor] = value

        # Write to InfluxDB
        write_to_influx(sensor, value, zone, node, ts)

        # Rules engine check
        alert = rules_engine(sensor, value)

        # Emit to dashboard
        payload = {
            "sensor":    sensor,
            "value":     value,
            "unit":      UNITS.get(sensor, ""),
            "zone":      zone,
            "node_id":   node,
            "timestamp": ts,
            "alert":     alert,
        }
        socketio.emit("sensor_update", payload)

    except Exception as e:
        print(f"[MQTT] Message error: {e}")


def setup_mqtt():
    client = mqtt.Client(client_id="mineguard-backend")
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        return client
    except Exception as e:
        print(f"[MQTT] Cannot connect: {e}")
        print("[MQTT] Backend will run without MQTT. Start broker and restart.")
        return None

# =============================================================================
#  REST API
# =============================================================================

@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "status":    "online",
        "timestamp": datetime.datetime.utcnow().isoformat(),
        "influx":    INFLUX_OK,
        "mongo":     MONGO_OK,
        "models":    MODELS_LOADED,
        "sensors":   len(latest_readings),
    })


@app.route("/api/readings/latest", methods=["GET"])
def api_latest():
    return jsonify({
        "readings":   {s: round(v, 4) for s, v in latest_readings.items()},
        "risk":       latest_risk,
        "alerts":     list(active_alerts.values()),
        "timestamp":  datetime.datetime.utcnow().isoformat(),
    })


@app.route("/api/alerts", methods=["GET"])
def api_alerts():
    if not MONGO_OK:
        return jsonify({"alerts": list(active_alerts.values())})
    try:
        recent = list(db.alerts.find({}, {"_id": 0})
                      .sort("timestamp", -1).limit(50))
        return jsonify({"alerts": recent})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/predictions", methods=["GET"])
def api_predictions():
    if not MONGO_OK:
        return jsonify({"predictions": [latest_risk] if latest_risk else []})
    try:
        recent = list(db.predictions.find({}, {"_id": 0})
                      .sort("timestamp", -1).limit(20))
        return jsonify({"predictions": recent})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/history/<sensor>", methods=["GET"])
def api_history(sensor):
    if sensor not in SENSOR_ORDER:
        return jsonify({"error": "Unknown sensor"}), 400
    buf = list(sensor_buffers[sensor])
    return jsonify({"sensor": sensor, "values": buf, "count": len(buf)})


# Health check
@app.route("/health")
def health():
    return "OK", 200


# =============================================================================
#  WEBSOCKET EVENTS
# =============================================================================

@socketio.on("connect")
def on_ws_connect():
    print("[WS] Client connected")
    # Send current state on connect
    socketio.emit("initial_state", {
        "readings":  {s: round(v, 4) for s, v in latest_readings.items()},
        "risk":      latest_risk,
        "alerts":    list(active_alerts.values()),
        "timestamp": datetime.datetime.utcnow().isoformat(),
    })


@socketio.on("disconnect")
def on_ws_disconnect():
    print("[WS] Client disconnected")

# =============================================================================
#  MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  MINEGUARD BACKEND  —  Starting up")
    print("=" * 60)

    # Start MQTT
    mqtt_client = setup_mqtt()

    # Start AI scheduler
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_ai_inference, "interval", seconds=AI_INTERVAL, id="ai_inference")
    scheduler.start()
    print(f"[Scheduler] AI inference every {AI_INTERVAL}s")

    print("\n[API] Endpoints:")
    print("  GET /api/status")
    print("  GET /api/readings/latest")
    print("  GET /api/alerts")
    print("  GET /api/predictions")
    print("  GET /api/history/<sensor>")
    print("\n[WS]  ws://localhost:5000  (Socket.IO)")
    print("=" * 60)

    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
