"""ML risk scoring engine.

Production-grade version pulls features from:
- Bureau (Circulo de Credito / Buró de Crédito)
- Internal payment history
- Bank transaction pattern analysis
- Employment verification APIs
- Behavioral / device fingerprinting

This implementation provides a *calibrated, deterministic* scoring function
that combines:
- Rule-based priors (document, biometric, KYC pass/fail)
- Logistic-regression-style score from demographic & financial features
- Reason-code generation for explainability

The surface (`score_application`) is stable — replace the internals with
your real model artifacts (pickle/joblib) without changing the API.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Dict, Any, List, Tuple, Optional
import numpy as np

from app.config import get_settings
from app.models import ApplicationStatus, RiskBand

settings = get_settings()
MODEL_VERSION = "rule-fusion-v1.0"


@dataclass
class RiskFeatures:
    # Demographic
    age: float = 35.0
    age_squared: float = 1225.0

    # Income / request
    monthly_income: float = 0.0
    requested_amount: float = 0.0
    income_to_amount_ratio: float = 0.0

    # Term
    term_months: float = 12.0
    term_risk_factor: float = 0.0

    # KYC priors (0..1 each)
    kyc_complete: float = 0.0
    documents_quality: float = 0.0
    biometric_quality: float = 0.0
    biometric_match: float = 0.0
    liveness_score: float = 0.0

    # External signals (mocked bureau)
    bureau_score_normalized: float = 0.5      # 0..1 (higher = better)
    delinquency_history: int = 0
    open_lines: int = 0

    # Behavioral
    application_velocity_30d: int = 0          # apps in last 30 days
    device_repeat: float = 0.0
    geographic_consistency: float = 1.0        # 1 = good

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class RiskResult:
    score: float                               # 0..1, higher = lower risk
    band: str                                  # AAA..D
    decision: str                              # AUTO_APPROVED / HUMAN_REVIEW / AUTO_REJECTED
    reasons: List[str]
    reasons_positive: List[str]
    features: Dict[str, float]
    model_version: str = MODEL_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "band": self.band,
            "decision": self.decision,
            "reasons": self.reasons,
            "reasons_positive": self.reasons_positive,
            "features": {k: round(v, 4) for k, v in self.features.items()},
            "model_version": self.model_version,
        }


# ----- Feature engineering -----
def build_features(app_dict: Dict[str, Any], biometric: Optional[Dict[str, Any]] = None) -> RiskFeatures:
    """Build feature vector from applicant + biometric + rule outcomes."""
    f = RiskFeatures()

    # demographic
    bd = app_dict.get("birth_date")
    if isinstance(bd, str):
        bd = date.fromisoformat(bd)
    if bd:
        today = date.today()
        f.age = (today - bd).days / 365.25
        f.age_squared = f.age ** 2

    # income / amount
    f.monthly_income = float(app_dict.get("monthly_income") or 0)
    f.requested_amount = float(app_dict.get("requested_amount") or 0)
    f.term_months = float(app_dict.get("requested_term_months") or 12)
    if f.monthly_income > 0 and f.requested_amount > 0:
        # ratio of (amount / (income * term)) — values near 0.4-0.6 are healthy
        f.income_to_amount_ratio = f.requested_amount / (f.monthly_income * max(f.term_months, 1))
    f.term_risk_factor = 1.0 / (1.0 + math.exp(-(f.term_months - 24) / 8))

    # KYC priors
    f.kyc_complete = 1.0 if app_dict.get("kyc_complete") else 0.0
    f.documents_quality = float(app_dict.get("documents_quality") or 0)
    if biometric:
        f.biometric_quality = float(biometric.get("face_quality") or 0)
        f.biometric_match = 1.0 if biometric.get("match_passed") else 0.0
        liv = biometric.get("liveness") or {}
        f.liveness_score = float(liv.get("score") or 0)

    # bureau — in production, fetches from Circulo de Credito
    f.bureau_score_normalized = float(app_dict.get("bureau_score") or 0.5)
    f.delinquency_history = int(app_dict.get("delinquency_history") or 0)
    f.open_lines = int(app_dict.get("open_lines") or 0)

    # behavioral
    f.application_velocity_30d = int(app_dict.get("application_velocity_30d") or 0)
    f.device_repeat = 1.0 if app_dict.get("device_repeat") else 0.0
    f.geographic_consistency = float(app_dict.get("geographic_consistency") or 1.0)

    return f


# ----- Model -----
class RiskModel:
    """
    Weighted logistic-style scoring function.

    Each feature contributes a weight. Output is squashed through sigmoid
    to [0, 1] range where 1 = lowest risk.

    In production: load weights from a persisted model artifact or call
    a remote model server (e.g. BentoML). The signature is stable.
    """

    WEIGHTS = {
        # Demographic
        "age":             0.012,
        "age_squared":     -0.00018,

        # Income / request
        "income_to_amount_ratio":  -0.85,
        "term_risk_factor":        -0.20,

        # KYC priors
        "kyc_complete":            0.55,
        "documents_quality":       0.45,
        "biometric_quality":       0.35,
        "biometric_match":         0.80,
        "liveness_score":          0.25,

        # Bureau
        "bureau_score_normalized": 1.10,
        "delinquency_history":    -0.45,
        "open_lines":             -0.05,

        # Behavioral
        "application_velocity_30d": -0.10,
        "device_repeat":           0.10,
        "geographic_consistency":  0.18,
    }

    INTERCEPT = -0.95

    @classmethod
    def score(cls, features: RiskFeatures) -> float:
        z = cls.INTERCEPT
        for k, w in cls.WEIGHTS.items():
            z += w * getattr(features, k)
        # sigmoid
        return 1.0 / (1.0 + math.exp(-z))


# ----- Explainability -----
def generate_reasons(features: RiskFeatures, score: float) -> Tuple[List[str], List[str]]:
    """Return (negative_reasons, positive_reasons) for explainability."""
    neg, pos = [], []

    if features.income_to_amount_ratio > 0.7:
        neg.append(f"Solicitud excede 70% del ingreso anual ({features.income_to_amount_ratio:.2f})")
    elif features.income_to_amount_ratio < 0.5 and features.monthly_income > 0:
        pos.append(f"Monto solicitado saludable vs ingresos ({features.income_to_amount_ratio:.2f})")

    if features.term_months > 36:
        neg.append(f"Plazo largo ({int(features.term_months)} meses)")

    if features.age < 25 or features.age > 65:
        neg.append(f"Edad fuera del rango óptimo ({int(features.age)})")
    elif 30 <= features.age <= 55:
        pos.append(f"Perfil de edad favorable ({int(features.age)})")

    if features.bureau_score_normalized >= 0.7:
        pos.append(f"Buró de crédito favorable ({features.bureau_score_normalized:.2f})")
    elif features.bureau_score_normalized < 0.4:
        neg.append(f"Buró de crédito bajo ({features.bureau_score_normalized:.2f})")

    if features.delinquency_history > 0:
        neg.append(f"Historial de morosidad ({features.delinquency_history} eventos)")

    if features.kyc_complete < 0.99:
        neg.append("KYC incompleto")
    else:
        pos.append("KYC verificado completo")

    if features.biometric_match < 1.0:
        neg.append("Biometría facial no coincide")
    else:
        pos.append("Biometría facial verificada")

    if features.application_velocity_30d > 3:
        neg.append(f"Velocidad de solicitudes alta ({features.application_velocity_30d}/30d)")

    if features.device_repeat:
        pos.append("Dispositivo previamente verificado")

    if features.geographic_consistency < 0.8:
        neg.append("Inconsistencia geográfica detectada")

    return neg, pos


# ----- Public API -----
def band_from_score(score: float) -> str:
    if score >= 0.85: return RiskBand.AAA.value
    if score >= 0.75: return RiskBand.AA.value
    if score >= 0.65: return RiskBand.A.value
    if score >= 0.55: return RiskBand.BBB.value
    if score >= 0.45: return RiskBand.BB.value
    if score >= 0.35: return RiskBand.B.value
    if score >= 0.20: return RiskBand.CCC.value
    return RiskBand.D.value


def decision_from_score(score: float, kyc_complete: bool = True, biometric_ok: bool = True) -> str:
    if not kyc_complete or not biometric_ok:
        return ApplicationStatus.HUMAN_REVIEW.value
    if score >= settings.risk_auto_approve_min:
        return ApplicationStatus.AUTO_APPROVED.value
    if score <= settings.risk_auto_reject_max:
        return ApplicationStatus.AUTO_REJECTED.value
    return ApplicationStatus.HUMAN_REVIEW.value


def score_application(
    application_dict: Dict[str, Any],
    biometric: Optional[Dict[str, Any]] = None,
) -> RiskResult:
    """Run the full risk scoring pipeline."""
    features = build_features(application_dict, biometric)
    raw_score = RiskModel.score(features)
    neg, pos = generate_reasons(features, raw_score)

    decision = decision_from_score(
        raw_score,
        kyc_complete=features.kyc_complete >= 1.0,
        biometric_ok=features.biometric_match >= 1.0 and features.liveness_score >= 0.55,
    )

    return RiskResult(
        score=raw_score,
        band=band_from_score(raw_score),
        decision=decision,
        reasons=neg if neg else ["Sin observaciones relevantes"],
        reasons_positive=pos if pos else [],
        features=features.to_dict(),
    )
