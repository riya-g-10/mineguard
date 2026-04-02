#!/usr/bin/env python3
"""
MineGuard — Full Setup & Activation Guide
==========================================
Run this script to check your environment and print step-by-step instructions.

    python setup_guide.py
"""

import sys
import subprocess
import os

SEP  = "=" * 65
SEP2 = "-" * 65

def check(name, cmd):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        ok = result.returncode == 0
        print(f"  {'✓' if ok else '✗'}  {name:<30} {'OK' if ok else 'MISSING'}")
        return ok
    except Exception:
        print(f"  ✗  {name:<30} MISSING")
        return False


def main():
    print(SEP)
    print("  MINEGUARD — ENVIRONMENT CHECK")
    print(SEP)

    py_ok      = check("Python 3.8+",          ["python3", "--version"])
    pip_ok     = check("pip",                   ["pip3", "--version"])
    mosquitto  = check("Mosquitto (MQTT)",      ["mosquitto", "-h"])
    influx     = check("InfluxDB",              ["influx", "version"])
    mongo      = check("MongoDB",               ["mongod", "--version"])

    print()
    print(SEP)
    print("  MINEGUARD — STEP-BY-STEP ACTIVATION GUIDE")
    print(SEP)

    print("""
┌─────────────────────────────────────────────────────────────┐
│  PREREQUISITES  (install once)                              │
└─────────────────────────────────────────────────────────────┘

  1. Python 3.8+
     sudo apt install python3 python3-pip     # Ubuntu/Raspberry Pi
     brew install python                       # Mac

  2. Mosquitto MQTT Broker
     sudo apt install mosquitto mosquitto-clients    # Ubuntu
     brew install mosquitto                           # Mac

  3. InfluxDB 2.x
     # Ubuntu:
     wget https://dl.influxdata.com/influxdb/releases/influxdb2_2.7.1_amd64.deb
     sudo dpkg -i influxdb2_2.7.1_amd64.deb

     # Mac:
     brew install influxdb

  4. MongoDB
     # Ubuntu:
     sudo apt install mongodb
     # Mac:
     brew install mongodb-community

┌─────────────────────────────────────────────────────────────┐
│  STEP 1 — Install Python dependencies                       │
└─────────────────────────────────────────────────────────────┘

  cd mineguard/
  pip install -r requirements.txt --break-system-packages

  If you're on Raspberry Pi:
  pip3 install -r requirements.txt --break-system-packages

┌─────────────────────────────────────────────────────────────┐
│  STEP 2 — Set up InfluxDB                                   │
└─────────────────────────────────────────────────────────────┘

  # Start InfluxDB
  sudo systemctl start influxdb    # Linux
  influxd                          # Mac (or run as service)

  # Open browser → http://localhost:8086
  # Create:
  #   Organisation : mineguard
  #   Bucket       : mineguard
  #   Username     : admin
  #   Password     : (your choice)
  #   API Token    : copy it → paste in backend/app.py as INFLUX_TOKEN
  #                  OR set environment variable: export INFLUX_TOKEN=your_token

┌─────────────────────────────────────────────────────────────┐
│  STEP 3 — Set up MongoDB                                    │
└─────────────────────────────────────────────────────────────┘

  # Start MongoDB (no config needed — default port 27017)
  sudo systemctl start mongod      # Linux
  brew services start mongodb-community   # Mac

  # MineGuard creates the 'mineguard' database automatically
  # on first write. No setup required.

┌─────────────────────────────────────────────────────────────┐
│  STEP 4 — Start MQTT Broker                                 │
└─────────────────────────────────────────────────────────────┘

  # Terminal 1 — keep this running
  mosquitto -v

  # You should see:
  #   mosquitto version X.X.X starting
  #   Opening ipv4 listen socket on port 1883.

┌─────────────────────────────────────────────────────────────┐
│  STEP 5 — Generate training data + train AI models         │
└─────────────────────────────────────────────────────────────┘

  # From the mineguard/ folder:

  # Generate 8000 synthetic readings
  python scripts/generate_training_data.py

  # Expected output:
  #   [OK] Generated 8000 readings → models/training_data.csv
  #   Safe: 4800  Warning: 2000  Danger: 1200

  # Train all 3 models (~30 seconds)
  python scripts/train_models.py

  # Expected output:
  #   [MODEL 1] Training IsolationForest...  Saved
  #   [MODEL 2] Training RandomForest...     Accuracy: ~0.97+
  #   [MODEL 3] Training GradientBoosting... Accuracy: ~0.96+
  #   [DONE] All models saved to models/

  # Files created:
  #   models/isolation_forest.pkl
  #   models/risk_classifier.pkl
  #   models/risk_scorer.pkl
  #   models/model_info.json

┌─────────────────────────────────────────────────────────────┐
│  STEP 6 — Start the Flask backend                           │
└─────────────────────────────────────────────────────────────┘

  # Terminal 2 — keep this running
  python backend/app.py

  # Expected output:
  #   [InfluxDB] Connected → http://localhost:8086
  #   [MongoDB]  Connected → mongodb://localhost:27017
  #   [AI] All models loaded.
  #   [MQTT] Connected to broker localhost:1883
  #   [MQTT] Subscribed to  mineguard/sensors/#
  #   [Scheduler] AI inference every 30s
  #   Running on  http://0.0.0.0:5000

  # Test it:
  #   http://localhost:5000/api/status   → should return {"status": "online"}
  #   http://localhost:5000/health       → should return OK

┌─────────────────────────────────────────────────────────────┐
│  STEP 7 — Start the sensor simulation                       │
└─────────────────────────────────────────────────────────────┘

  # Terminal 3 — keep this running
  python simulation.py

  # Expected output:
  #   [MQTT] Connected to broker (rc=0)
  #   Reading #1 ...  ALL SENSORS NORMAL
  #   [MQTT] Published reading #1 → broker (status: SAFE)

  # Every 3 seconds a reading is published.
  # The backend receives it, writes to InfluxDB/MongoDB,
  # runs the rules engine, and pushes to the dashboard.

┌─────────────────────────────────────────────────────────────┐
│  STEP 8 — Open the dashboard                                │
└─────────────────────────────────────────────────────────────┘

  Open your dashboard HTML file in a browser.
  Make sure the Socket.IO URL in the dashboard JS points to:
    http://localhost:5000

  Example Socket.IO connection in your dashboard JS:
    const socket = io('http://localhost:5000');

    socket.on('sensor_update', (data) => {
        // update the metric cards
        console.log(data);
    });

    socket.on('ai_update', (data) => {
        // update risk score + advisories
        console.log(data);
    });

┌─────────────────────────────────────────────────────────────┐
│  TERMINAL LAYOUT (4 terminals open simultaneously)         │
└─────────────────────────────────────────────────────────────┘

  Terminal 1:  mosquitto -v
  Terminal 2:  python backend/app.py
  Terminal 3:  python simulation.py
  Terminal 4:  (free for testing / queries)

┌─────────────────────────────────────────────────────────────┐
│  ENVIRONMENT VARIABLES (optional, override defaults)        │
└─────────────────────────────────────────────────────────────┘

  export MQTT_BROKER=localhost
  export MQTT_PORT=1883
  export INFLUX_URL=http://localhost:8086
  export INFLUX_TOKEN=your_influxdb_token_here
  export INFLUX_ORG=mineguard
  export INFLUX_BUCKET=mineguard
  export MONGO_URI=mongodb://localhost:27017
  export MONGO_DB=mineguard
  export AI_INTERVAL=30

┌─────────────────────────────────────────────────────────────┐
│  TROUBLESHOOTING                                            │
└─────────────────────────────────────────────────────────────┘

  [MQTT] Connection refused
    → Mosquitto not running. Run:  mosquitto -v

  [InfluxDB] Not available
    → Check token is correct. Check influxd is running.
    → Try:  curl http://localhost:8086/health

  [MongoDB] Not available
    → Run:  sudo systemctl start mongod
    → or:   mongod --dbpath /tmp/mineguard-db

  [AI] Models not found
    → Run:  python scripts/generate_training_data.py
    → Then: python scripts/train_models.py

  Port 5000 in use
    → Kill the process:  lsof -ti:5000 | xargs kill
    → Or change port in backend/app.py last line

  Dashboard not receiving data
    → Check browser console for Socket.IO errors
    → Make sure io() URL matches backend address
    → Check CORS is enabled (it is by default in app.py)

┌─────────────────────────────────────────────────────────────┐
│  API ENDPOINTS REFERENCE                                    │
└─────────────────────────────────────────────────────────────┘

  GET /health                   → "OK"
  GET /api/status               → system status + connections
  GET /api/readings/latest      → all sensor values + AI risk + alerts
  GET /api/alerts               → last 50 alerts from MongoDB
  GET /api/predictions          → last 20 AI predictions
  GET /api/history/<sensor>     → buffered readings for one sensor
                                   e.g. /api/history/ch4

  WebSocket events (from server → dashboard):
    sensor_update   → {sensor, value, unit, zone, alert}
    ai_update       → {risk_score, risk_level, advisories, ...}
    initial_state   → sent on connect, full current state
""")

    print(SEP)
    print("  FOLDER STRUCTURE")
    print(SEP)
    print("""
  mineguard/
  ├── simulation.py              ← sensor simulator (run last)
  ├── requirements.txt           ← pip dependencies
  ├── setup_guide.py             ← this file
  ├── backend/
  │   └── app.py                 ← Flask + MQTT + AI + WebSocket
  ├── models/
  │   ├── training_data.csv      ← generated by generate_training_data.py
  │   ├── isolation_forest.pkl   ← anomaly detector
  │   ├── risk_classifier.pkl    ← 3-class risk model
  │   ├── risk_scorer.pkl        ← probability scorer
  │   └── model_info.json        ← feature/threshold metadata
  └── scripts/
      ├── generate_training_data.py
      └── train_models.py
""")
    print(SEP)
    print("  Ready. Follow steps 1–8 above in order.")
    print(SEP)


if __name__ == "__main__":
    main()
