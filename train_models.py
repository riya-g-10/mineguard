"""
MineGuard — Model Training Script
===================================
Trains three models:
  1. IsolationForest   — anomaly / spike detection  (unsupervised)
  2. RandomForest      — gas + structural risk classification (0=safe,1=warn,2=danger)
  3. GradientBoosting  — risk probability score (0.0 – 1.0)

Run AFTER generate_training_data.py:
  python scripts/train_models.py
"""

import os
import json
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, IsolationForest, GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, accuracy_score
from sklearn.pipeline import Pipeline
import joblib

DATA_FILE  = os.path.join(os.path.dirname(__file__), "..", "models", "training_data.csv")
MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")
FEATURES   = ["ch4", "co", "h2s", "co2", "o2", "seismic"]


def load_data():
    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(
            f"Training data not found: {DATA_FILE}\n"
            "Run:  python scripts/generate_training_data.py  first."
        )
    df = pd.read_csv(DATA_FILE)
    print(f"[DATA] Loaded {len(df)} rows")
    print(f"[DATA] Label distribution:\n{df['label'].value_counts().sort_index().to_string()}\n")
    return df


def train_isolation_forest(X_safe):
    """Train on the safest samples — use low-risk rows as 'normal'."""
    print("[MODEL 1] Training IsolationForest (anomaly detection)...")
    if len(X_safe) == 0:
        print("  [WARN] No label-0 rows — using full dataset for IsolationForest")
        X_safe_use = X_safe   # will use fallback below
    else:
        X_safe_use = X_safe

    # Fallback: if no safe-only rows, use everything
    if len(X_safe_use) < 10:
        print("  [WARN] Too few safe samples — fitting IsolationForest on all data")
        X_safe_use = None   # handled below

    model = IsolationForest(
        n_estimators=200,
        contamination=0.1,
        random_state=42,
        n_jobs=-1
    )

    if X_safe_use is not None and len(X_safe_use) >= 10:
        model.fit(X_safe_use)
        print(f"  Fitted on {len(X_safe_use)} safe samples")
    else:
        # Last resort — will be passed by caller
        raise RuntimeError("Caller must pass valid X_safe or X_all")

    path = os.path.join(MODELS_DIR, "isolation_forest.pkl")
    joblib.dump(model, path)
    print(f"  Saved → {path}\n")
    return model


def train_random_forest(X_train, X_test, y_train, y_test):
    print("[MODEL 2] Training RandomForestClassifier (risk classification)...")
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf",    RandomForestClassifier(
            n_estimators=200,
            max_depth=12,
            min_samples_split=5,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1
        ))
    ])
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)
    acc    = accuracy_score(y_test, y_pred)
    labels_present = sorted(set(y_test) | set(y_pred))
    names  = [['SAFE','WARNING','DANGER'][i] for i in labels_present]
    print(f"  Accuracy : {acc:.4f}")
    print(f"  Report   :\n{classification_report(y_test, y_pred, labels=labels_present, target_names=names)}")
    path = os.path.join(MODELS_DIR, "risk_classifier.pkl")
    joblib.dump(pipeline, path)
    print(f"  Saved → {path}\n")
    return pipeline


def train_risk_scorer(X_train, X_test, y_train, y_test):
    """Binary: 0=no danger, 1=danger — outputs probability 0.0–1.0."""
    print("[MODEL 3] Training GradientBoostingClassifier (risk probability scorer)...")
    y_bin_train = (y_train >= 1).astype(int)   # 1 = warning or danger
    y_bin_test  = (y_test  >= 1).astype(int)

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf",    GradientBoostingClassifier(
            n_estimators=150,
            learning_rate=0.05,
            max_depth=5,
            random_state=42
        ))
    ])
    pipeline.fit(X_train, y_bin_train)
    y_prob = pipeline.predict_proba(X_test)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)
    acc    = accuracy_score(y_bin_test, y_pred)
    print(f"  Binary Accuracy : {acc:.4f}")
    path = os.path.join(MODELS_DIR, "risk_scorer.pkl")
    joblib.dump(pipeline, path)
    print(f"  Saved → {path}\n")
    return pipeline


def save_metadata(label_set):
    info = {
        "features":    FEATURES,
        "label_map":   {0: "SAFE", 1: "WARNING", 2: "DANGER"},
        "labels_in_data": sorted([int(l) for l in label_set]),
        "thresholds": {
            "ch4":     {"warning": 1.0,   "danger": 2.5},
            "co":      {"warning": 25,    "danger": 100},
            "h2s":     {"warning": 1,     "danger": 10},
            "co2":     {"warning": 0.5,   "danger": 1.5},
            "o2":      {"warning": 19.5,  "danger": 16.0},
            "seismic": {"warning": 2.0,   "danger": 3.5},
        }
    }
    path = os.path.join(MODELS_DIR, "model_info.json")
    with open(path, "w") as f:
        json.dump(info, f, indent=2)
    print(f"[INFO] Metadata saved → {path}")


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    df = load_data()

    X = df[FEATURES].values
    y = df["label"].values

    # IsolationForest: use the least-risky samples (label=0 if present, else label=1)
    if (y == 0).sum() >= 10:
        X_safe = df[df["label"] == 0][FEATURES].values
        print(f"[ISO] Using {len(X_safe)} label-0 (safe) samples for anomaly baseline")
    elif (y == 1).sum() >= 10:
        X_safe = df[df["label"] == 1][FEATURES].values
        print(f"[ISO] No label-0 rows — using {len(X_safe)} label-1 (warning) samples as baseline")
    else:
        X_safe = X
        print(f"[ISO] Using all {len(X_safe)} samples as baseline")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Train all three
    iso_model = IsolationForest(n_estimators=200, contamination=0.1, random_state=42, n_jobs=-1)
    iso_model.fit(X_safe)
    iso_path  = os.path.join(MODELS_DIR, "isolation_forest.pkl")
    joblib.dump(iso_model, iso_path)
    print(f"[MODEL 1] IsolationForest trained on {len(X_safe)} samples → {iso_path}\n")

    train_random_forest(X_train, X_test, y_train, y_test)
    train_risk_scorer(X_train, X_test, y_train, y_test)
    save_metadata(set(y))

    print("\n[DONE] All models trained and saved to models/")
    print("       Start the backend:  python backend/app.py")


if __name__ == "__main__":
    main()
