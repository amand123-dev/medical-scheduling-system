"""
Train a RandomForestClassifier on the Kaggle Medical No-Show dataset.

Dataset: https://www.kaggle.com/datasets/joniarroba/noshowappointments
  - Download the CSV and place it at backend/data/KaggleV2-May-2016.csv
  - Or pass a custom path via the DATA_PATH environment variable.

Output: backend/models/noshow_rf.joblib

Usage:
    python scripts/train_noshow.py
    DATA_PATH=/path/to/file.csv python scripts/train_noshow.py

Note: This model is NOT wired into live appointment creation. Operational
tables intentionally omit the demographic features (age, chronic conditions)
required for inference — data-minimization by design. The trained model is
exposed only via POST /scorer/predict for portfolio demonstration.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Resolve paths relative to this script, regardless of cwd
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
DEFAULT_DATA_PATH = BACKEND_DIR / "data" / "no_show_appointments.csv"
MODEL_OUTPUT = BACKEND_DIR / "models" / "noshow_rf.joblib"

DATA_PATH = Path(os.environ.get("DATA_PATH", DEFAULT_DATA_PATH))


def main() -> None:
    try:
        import joblib
        import pandas as pd
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.metrics import roc_auc_score
        from sklearn.model_selection import train_test_split
    except ImportError as exc:
        print(f"Missing dependency: {exc}")
        print("Run: pip install scikit-learn pandas joblib numpy")
        sys.exit(1)

    if not DATA_PATH.exists():
        print(f"Dataset not found at {DATA_PATH}")
        print("Download from https://www.kaggle.com/datasets/joniarroba/noshowappointments")
        print(f"and place at {DEFAULT_DATA_PATH} (or set DATA_PATH env var)")
        sys.exit(1)

    print(f"Loading dataset from {DATA_PATH} ...")
    df = pd.read_csv(DATA_PATH)

    # ── Feature engineering ──────────────────────────────────────────────────
    df["ScheduledDay"] = pd.to_datetime(df["ScheduledDay"])
    df["AppointmentDay"] = pd.to_datetime(df["AppointmentDay"])
    df["wait_days"] = (df["AppointmentDay"] - df["ScheduledDay"]).dt.days.clip(lower=0)

    # Encode Gender: F → 1, M → 0 (must match app/scorer/ml.py encoding)
    df["Gender"] = (df["Gender"] == "F").astype(int)

    # Target: "No-show" column → binary (Yes=1, No=0)
    target_col = "No-show"
    df[target_col] = (df[target_col] == "Yes").astype(int)

    feature_cols = [
        "Age",
        "Gender",
        "Scholarship",
        "Hipertension",
        "Diabetes",
        "Alcoholism",
        "Handcap",
        "SMS_received",
        "wait_days",
    ]

    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        print(f"Missing columns in CSV: {missing}")
        print(f"Available columns: {list(df.columns)}")
        sys.exit(1)

    X = df[feature_cols].values
    y = df[target_col].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print(
        f"Training on {len(X_train):,} rows, evaluating on {len(X_test):,} rows"
        f" ({y.mean():.1%} no-show rate)"
    )

    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        min_samples_leaf=20,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    # ── Evaluation ────────────────────────────────────────────────────────────
    acc = clf.score(X_test, y_test)
    proba = clf.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, proba)

    print(f"Accuracy : {acc:.4f}")
    print(f"AUC-ROC  : {auc:.4f}")

    # Feature importance summary
    importances = sorted(
        zip(feature_cols, clf.feature_importances_, strict=True), key=lambda x: x[1], reverse=True
    )
    print("\nFeature importances:")
    for name, imp in importances:
        bar = "█" * int(imp * 40)
        print(f"  {name:<15} {imp:.4f}  {bar}")

    # ── Save ─────────────────────────────────────────────────────────────────
    MODEL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, MODEL_OUTPUT)
    print(f"\nModel saved to {MODEL_OUTPUT}")
    print(
        "\nNote: This model requires demographic features not stored in operational "
        "tables (data minimization by design). Use POST /scorer/predict for demo only."
    )


if __name__ == "__main__":
    main()
