"""SQLAlchemy models for the KYC platform."""
import uuid
from datetime import datetime, timezone
import enum

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Date,
    ForeignKey, Enum, JSON, Index, Text, Numeric, LargeBinary
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base


def utcnow():
    return datetime.now(timezone.utc)


def gen_uuid():
    return str(uuid.uuid4())


# ----- Enums -----
class ApplicationStatus(str, enum.Enum):
    PENDING = "pending"
    KYC_IN_PROGRESS = "kyc_in_progress"
    BIOMETRIC_PENDING = "biometric_pending"
    RISK_EVALUATION = "risk_evaluation"
    AUTO_APPROVED = "auto_approved"
    AUTO_REJECTED = "auto_rejected"
    HUMAN_REVIEW = "human_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class RiskBand(str, enum.Enum):
    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"
    B = "B"
    CCC = "CCC"
    D = "D"


class DocumentType(str, enum.Enum):
    INE_FRONT = "ine_front"
    INE_BACK = "ine_back"
    CURP = "curp"
    PROOF_OF_ADDRESS = "proof_of_address"
    SELFIE = "selfie"
    BANK_STATEMENT = "bank_statement"
    TAX_ID = "tax_id"
    OTHER = "other"


class BiometricStatus(str, enum.Enum):
    PENDING = "pending"
    CAPTURED = "captured"
    QUALITY_OK = "quality_ok"
    QUALITY_FAIL = "quality_fail"
    LIVENESS_OK = "liveness_ok"
    LIVENESS_FAIL = "liveness_fail"
    MATCH_OK = "match_ok"
    MATCH_FAIL = "match_fail"
    VERIFIED = "verified"
    REJECTED = "rejected"


class KycStep(str, enum.Enum):
    INITIAL = "initial"
    PERSONAL_DATA = "personal_data"
    DOCUMENTS = "documents"
    BIOMETRIC = "biometric"
    RISK_SCORING = "risk_scoring"
    FINAL_DECISION = "final_decision"


# ----- Models -----
class Applicant(Base):
    """Person applying for credit. PII fields encrypted at rest in production."""
    __tablename__ = "applicants"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    external_id = Column(String(64), unique=True, index=True, nullable=True)

    # PII
    first_name = Column(String(120), nullable=False)
    last_name = Column(String(120), nullable=False)
    second_last_name = Column(String(120), nullable=True)
    birth_date = Column(Date, nullable=False)
    curp = Column(String(18), unique=True, index=True, nullable=False)
    rfc = Column(String(13), nullable=True)
    email = Column(String(180), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=False)

    # Address
    address_line = Column(String(255), nullable=True)
    address_city = Column(String(120), nullable=True)
    address_state = Column(String(80), nullable=True)
    address_zip = Column(String(10), nullable=True)
    address_country = Column(String(2), default="MX", nullable=False)

    # Financial profile
    monthly_income = Column(Numeric(14, 2), nullable=True)
    employment_status = Column(String(60), nullable=True)
    employer = Column(String(180), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    applications = relationship("Application", back_populates="applicant", cascade="all,delete")
    documents = relationship("Document", back_populates="applicant", cascade="all,delete")
    biometrics = relationship("BiometricCheck", back_populates="applicant", cascade="all,delete")


class Application(Base):
    """Credit origination application."""
    __tablename__ = "applications"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    applicant_id = Column(String(36), ForeignKey("applicants.id"), nullable=False, index=True)

    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.PENDING, nullable=False, index=True)
    kyc_step = Column(Enum(KycStep), default=KycStep.INITIAL, nullable=False)

    requested_amount = Column(Numeric(14, 2), nullable=False)
    requested_term_months = Column(Integer, nullable=False)
    product_type = Column(String(60), nullable=False)
    purpose = Column(Text, nullable=True)

    # ML risk output
    risk_score = Column(Float, nullable=True)              # 0.0 - 1.0 (1 = low risk)
    risk_band = Column(Enum(RiskBand), nullable=True)
    risk_model_version = Column(String(32), nullable=True)
    risk_features = Column(JSON, nullable=True)
    risk_reasons = Column(JSON, nullable=True)             # list of strings

    # Decision timing
    kyc_started_at = Column(DateTime(timezone=True), nullable=True)
    decision_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    applicant = relationship("Applicant", back_populates="applications")
    documents = relationship("Document", back_populates="application", cascade="all,delete")
    biometrics = relationship("BiometricCheck", back_populates="application", cascade="all,delete")
    audit_logs = relationship("AuditLog", back_populates="application", cascade="all,delete")


class Document(Base):
    """KYC document (INE, CURP, proof of address, etc)."""
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    applicant_id = Column(String(36), ForeignKey("applicants.id"), nullable=False, index=True)
    application_id = Column(String(36), ForeignKey("applications.id"), nullable=False, index=True)

    document_type = Column(Enum(DocumentType), nullable=False)
    file_hash_sha256 = Column(String(64), nullable=False, index=True)
    file_path = Column(String(512), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String(60), nullable=True)

    # OCR / validation results
    extracted_fields = Column(JSON, nullable=True)
    validation_status = Column(String(20), default="pending", nullable=False)
    validation_score = Column(Float, nullable=True)
    validation_errors = Column(JSON, nullable=True)

    uploaded_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)

    applicant = relationship("Applicant", back_populates="documents")
    application = relationship("Application", back_populates="documents")


class BiometricCheck(Base):
    """Facial recognition + liveness detection result."""
    __tablename__ = "biometric_checks"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    applicant_id = Column(String(36), ForeignKey("applicants.id"), nullable=False, index=True)
    application_id = Column(String(36), ForeignKey("applications.id"), nullable=False, index=True)

    status = Column(Enum(BiometricStatus), default=BiometricStatus.PENDING, nullable=False)

    # Quality
    face_quality = Column(Float, nullable=True)            # 0..1
    face_bbox = Column(JSON, nullable=True)                # [x, y, w, h]
    face_landmarks = Column(Integer, nullable=True)        # count of detected points

    # Liveness
    liveness_passed = Column(Boolean, nullable=True)
    liveness_score = Column(Float, nullable=True)
    liveness_method = Column(String(40), nullable=True)    # passive/active/iProov

    # Match against document selfie
    match_score = Column(Float, nullable=True)             # 0..1 cosine similarity
    match_threshold = Column(Float, nullable=True)
    match_passed = Column(Boolean, nullable=True)

    # Encoded vector (in production, store encrypted)
    face_encoding = Column(JSON, nullable=True)

    attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    applicant = relationship("Applicant", back_populates="biometrics")
    application = relationship("Application", back_populates="biometrics")


class AuditLog(Base):
    """Full traceability — every step recorded."""
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    application_id = Column(String(36), ForeignKey("applications.id"), nullable=False, index=True)

    step = Column(String(60), nullable=False, index=True)
    action = Column(String(60), nullable=False)
    actor = Column(String(60), nullable=False)            # "system", "reviewer@...", applicant_id
    actor_type = Column(String(20), nullable=False)        # "system" / "human" / "applicant"

    details = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)

    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    application = relationship("Application", back_populates="audit_logs")


class Reviewer(Base):
    """Human reviewer for exception cases."""
    __tablename__ = "reviewers"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    username = Column(String(60), unique=True, index=True, nullable=False)
    email = Column(String(180), unique=True, nullable=False)
    full_name = Column(String(180), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(40), default="reviewer", nullable=False)   # reviewer / admin
    is_active = Column(Boolean, default=True, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


# ----- Indices -----
Index("ix_app_status_created", Application.status, Application.created_at)
Index("ix_app_decision_time", Application.decision_at)
Index("ix_biometric_app_status", BiometricCheck.application_id, BiometricCheck.status)
