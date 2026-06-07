"""
Demo-only ML scorer for no-show risk.

Trained on the public Kaggle Medical No-Show dataset
(https://www.kaggle.com/datasets/joniarroba/noshowappointments).

NOT wired into live appointment creation — the operational schema intentionally
omits the demographic features (age, chronic conditions, SMS_received) that the
Kaggle model requires. This endpoint exists as a portfolio demo: given a feature
dict matching the Kaggle columns, return a predicted no-show probability.

Run scripts/train_noshow.py first to produce models/noshow_rf.joblib.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# joblib / sklearn are optional at import time; the endpoint returns 503 if absent.
try:
    import joblib
    import numpy as np

    _JOBLIB_AVAILABLE = True
except ImportError:
    _JOBLIB_AVAILABLE = False

MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / "noshow_rf.joblib"

FEATURE_COLUMNS = [
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

_model: Any = None


def get_model() -> Any | None:
    """Lazily load the trained model. Returns None if not available."""
    global _model
    if not _JOBLIB_AVAILABLE:
        return None
    if _model is None:
        if not MODEL_PATH.exists():
            return None
        _model = joblib.load(MODEL_PATH)
    return _model


def predict(features: dict) -> float | None:
    """
    Return P(no-show) in [0, 1], or None if the model file is not present.

    features must contain keys matching FEATURE_COLUMNS. Gender is encoded
    as 1 (Female) / 0 (Male) to match training encoding.
    """
    model = get_model()
    if model is None:
        return None
    row = [features.get(col, 0) for col in FEATURE_COLUMNS]
    proba = model.predict_proba(np.array([row]))[0]
    # class order: [no_show=0, no_show=1] — return P(no-show)
    classes = list(model.classes_)
    no_show_idx = classes.index(1) if 1 in classes else -1
    return float(proba[no_show_idx]) if no_show_idx >= 0 else float(proba[1])
