"""KYC validation service - validates PII, CURP/RFC structure, document OCR."""
from __future__ import annotations
import re
from datetime import date, datetime
from typing import Dict, Any, Optional, Tuple, List

from app.config import get_settings

settings = get_settings()


# --- CURP validation (RENAPO format) ---
def validate_curp(curp: str) -> Tuple[bool, Optional[str]]:
    """
    CURP structure: 4 letters + 6 digits + 1 letter (H/M) + 5 letters + 2 alphanum
    Example: AAAA000101HMCLNS08
    """
    curp = curp.upper().strip()
    pattern = r"^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]{2}$"
    if not re.match(pattern, curp):
        return False, "INVALID_FORMAT"

    # Date validation inside CURP
    try:
        yy = int(curp[4:6])
        mm = int(curp[6:8])
        dd = int(curp[8:10])
        year = 1900 + yy if yy >= 30 else 2000 + yy
        d = date(year, mm, dd)
        # age check
        today = date.today()
        age = (today - d).days / 365.25
        if age < settings.kyc_min_age:
            return False, f"UNDER_AGE_{settings.kyc_min_age}"
        if age > settings.kyc_max_age:
            return False, f"OVER_AGE_{settings.kyc_max_age}"
    except ValueError:
        return False, "INVALID_DATE"

    return True, None


# --- RFC validation ---
def validate_rfc(rfc: str) -> Tuple[bool, Optional[str]]:
    rfc = rfc.upper().strip()
    # Persona moral: 3 letters + 6 digits + 3 alphanum
    # Persona fisica: 4 letters + 6 digits + 3 alphanum
    pattern = r"^([A-Z&]{3,4})\d{6}([A-Z0-9]{3})$"
    if not re.match(pattern, rfc):
        return False, "INVALID_FORMAT"
    return True, None


# --- INE validation (mock OCR extraction) ---
def validate_ine_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    In production this would call an OCR + RENAPO/INE cross-check API.
    Here we do structural validation.
    """
    errors = []
    score = 1.0

    required = ["nombre", "apellido_paterno", "domicilio", "clave_elector"]
    for r in required:
        if r not in payload or not payload[r]:
            errors.append(f"MISSING_FIELD_{r}")
            score -= 0.2

    # Clave de elector: 6 digits + 6 alphanumeric
    if "clave_elector" in payload:
        if not re.match(r"^\d{6}[A-Z0-9]{6}$", str(payload["clave_elector"]).upper()):
            errors.append("INVALID_CLAVE_ELECTOR")
            score -= 0.15

    return {
        "score": max(score, 0.0),
        "errors": errors,
        "extracted": payload,
    }


# --- Email validation ---
def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email))


# --- Phone (MX) ---
def normalize_phone(phone: str) -> Optional[str]:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        return f"+52{digits}"
    if len(digits) == 12 and digits.startswith("52"):
        return f"+{digits}"
    if len(digits) == 13 and digits.startswith("521"):
        return f"+{digits}"
    return None


# --- State rules ---
def run_business_rules(applicant_dict: Dict[str, Any], amount: float) -> Tuple[bool, List[str]]:
    """Hard business rules. Return (passed, list_of_reasons_if_failed)."""
    reasons = []

    # Sanctions list (mock)
    sanctioned = ["XEXX010101HNEXX4A", "BLACKLISTEDID001"]
    if applicant_dict.get("rfc") in sanctioned:
        reasons.append("RFC_SANCTIONED")

    # Income vs requested amount ratio
    if applicant_dict.get("monthly_income"):
        income = float(applicant_dict["monthly_income"])
        if income > 0 and amount > income * 36:
            reasons.append("AMOUNT_EXCEEDS_36_MONTHS_INCOME")

    # Country restrictions
    country = applicant_dict.get("address_country", "MX")
    if country not in ("MX", "US"):
        reasons.append(f"COUNTRY_NOT_SUPPORTED_{country}")

    return (len(reasons) == 0, reasons)
