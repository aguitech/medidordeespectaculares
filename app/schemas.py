"""Pydantic schemas for request/response validation."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict, Any
from enum import Enum

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------- Applicant ----------
class ApplicantCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(..., min_length=1, max_length=120)
    second_last_name: Optional[str] = Field(None, max_length=120)
    birth_date: date
    curp: str = Field(..., min_length=18, max_length=18, pattern=r"^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]{2}$")
    rfc: Optional[str] = Field(None, min_length=12, max_length=13)
    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=20)

    address_line: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_zip: Optional[str] = None
    address_country: str = "MX"

    monthly_income: Optional[Decimal] = None
    employment_status: Optional[str] = None
    employer: Optional[str] = None

    @field_validator("curp")
    @classmethod
    def _curp_upper(cls, v: str) -> str:
        return v.upper().strip()


class ApplicantOut(ApplicantCreate):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------- Application ----------
class ApplicationCreate(BaseModel):
    applicant_id: str
    requested_amount: Decimal = Field(..., gt=0)
    requested_term_months: int = Field(..., ge=1, le=120)
    product_type: str = Field(..., description="credit, leasing, mortgage, line_of_credit, etc")
    purpose: Optional[str] = None


class ApplicationOut(BaseModel):
    id: str
    applicant_id: str
    status: str
    kyc_step: str
    requested_amount: Decimal
    requested_term_months: int
    product_type: str

    risk_score: Optional[float] = None
    risk_band: Optional[str] = None
    risk_reasons: Optional[List[str]] = None
    risk_model_version: Optional[str] = None

    kyc_started_at: Optional[datetime] = None
    decision_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApplicationDecision(BaseModel):
    """Final decision."""
    decision: str = Field(..., description="approved | rejected | needs_more_info")
    notes: Optional[str] = None
    reviewer_id: str


# ---------- Biometric ----------
class BiometricCaptureRequest(BaseModel):
    application_id: str
    image_base64: str = Field(..., description="base64-encoded selfie image")


class BiometricOut(BaseModel):
    id: str
    status: str
    face_quality: Optional[float] = None
    liveness_passed: Optional[bool] = None
    liveness_score: Optional[float] = None
    match_passed: Optional[bool] = None
    match_score: Optional[float] = None
    attempts: int

    class Config:
        from_attributes = True


# ---------- Document ----------
class DocumentOut(BaseModel):
    id: str
    document_type: str
    file_hash_sha256: str
    file_size_bytes: Optional[int] = None
    validation_status: str
    validation_score: Optional[float] = None
    extracted_fields: Optional[Dict[str, Any]] = None
    uploaded_at: datetime
    verified_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Risk ----------
class RiskEvaluationRequest(BaseModel):
    application_id: str


class RiskEvaluationOut(BaseModel):
    application_id: str
    risk_score: float
    risk_band: str
    decision: str
    reasons: List[str]
    features: Dict[str, float]
    model_version: str
    duration_seconds: int
    evaluated_at: datetime


# ---------- Auth ----------
class ReviewerLogin(BaseModel):
    username: str
    password: str


class ReviewerOut(BaseModel):
    id: str
    username: str
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    reviewer: ReviewerOut


# ---------- Generic ----------
class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    database: str
    redis: str
    timestamp: datetime


class ErrorOut(BaseModel):
    error: str
    detail: Optional[str] = None
    request_id: Optional[str] = None
