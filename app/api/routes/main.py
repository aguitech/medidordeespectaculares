"""Health, KYC, applications, biometric, risk endpoints."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.db import get_db, engine
from app.config import get_settings
from app.models import (
    Applicant, Application, Document, BiometricCheck, AuditLog,
    ApplicationStatus, BiometricStatus, DocumentType, KycStep, Reviewer
)
from app.services.kyc import validate_curp, validate_rfc, normalize_phone
from app.services.biometric import verify_biometric, hash_image, assess_quality
from app.services.risk import score_application, MODEL_VERSION
import app.schemas as schemas

router = APIRouter()
settings = get_settings()


# ---------- Health ----------
@router.get("/health", response_model=schemas.HealthOut, tags=["system"])
def health(db: Session = Depends(get_db)):
    """Liveness + DB + Redis probe."""
    db_ok = "down"
    try:
        db.execute(func.now())
        db_ok = "up"
    except Exception:
        pass
    redis_ok = "n/a"
    if settings.redis_url:
        try:
            import redis
            r = redis.from_url(settings.redis_url, socket_connect_timeout=2)
            r.ping()
            redis_ok = "up"
        except Exception:
            redis_ok = "down"

    return {
        "status": "ok" if db_ok == "up" else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "database": db_ok,
        "redis": redis_ok,
        "timestamp": datetime.now(timezone.utc),
    }


# ---------- Applicants ----------
@router.post("/applicants", response_model=schemas.ApplicantOut, status_code=status.HTTP_201_CREATED, tags=["kyc"])
def create_applicant(payload: schemas.ApplicantCreate, db: Session = Depends(get_db), request: Request = None):
    """Step 1 — Collect personal data + CURP/RFC validation."""
    # Re-validate (defense in depth)
    curp_ok, err = validate_curp(payload.curp)
    if not curp_ok:
        raise HTTPException(400, detail=f"CURP_INVALID: {err}")
    if payload.rfc:
        rfc_ok, err = validate_rfc(payload.rfc)
        if not rfc_ok:
            raise HTTPException(400, detail=f"RFC_INVALID: {err}")
    phone = normalize_phone(payload.phone)
    if not phone:
        raise HTTPException(400, detail="PHONE_INVALID")

    # Duplicate check
    if db.query(Applicant).filter(Applicant.curp == payload.curp.upper()).first():
        raise HTTPException(409, detail="APPLICANT_ALREADY_EXISTS")

    if db.query(Applicant).filter(Applicant.email == str(payload.email)).first():
        raise HTTPException(409, detail="EMAIL_ALREADY_REGISTERED")

    applicant = Applicant(
        first_name=payload.first_name.upper(),
        last_name=payload.last_name.upper(),
        second_last_name=payload.second_last_name.upper() if payload.second_last_name else None,
        birth_date=payload.birth_date,
        curp=payload.curp.upper(),
        rfc=payload.rfc.upper() if payload.rfc else None,
        email=str(payload.email),
        phone=phone,
        address_line=payload.address_line,
        address_city=payload.address_city,
        address_state=payload.address_state,
        address_zip=payload.address_zip,
        address_country=payload.address_country,
        monthly_income=payload.monthly_income,
        employment_status=payload.employment_status,
        employer=payload.employer,
    )
    db.add(applicant)
    db.commit()
    db.refresh(applicant)

    # Audit
    db.add(AuditLog(
        application_id=applicant.id,  # log against applicant for now
        step="kyc.personal_data",
        action="CREATE_APPLICANT",
        actor=applicant.id,
        actor_type="applicant",
        details={"curp": "***masked***"},
        ip_address=(request.client.host if request and request.client else None),
    ))
    db.commit()

    return applicant


@router.get("/applicants/{applicant_id}", response_model=schemas.ApplicantOut, tags=["kyc"])
def get_applicant(applicant_id: str, db: Session = Depends(get_db)):
    a = db.query(Applicant).filter(Applicant.id == applicant_id).first()
    if not a:
        raise HTTPException(404, detail="APPLICANT_NOT_FOUND")
    return a


# ---------- Applications ----------
@router.post("/applications", response_model=schemas.ApplicationOut, status_code=status.HTTP_201_CREATED, tags=["kyc"])
def create_application(payload: schemas.ApplicationCreate, db: Session = Depends(get_db), request: Request = None):
    """Step 2 — Start credit application. Mandatory field validation."""
    applicant = db.query(Applicant).filter(Applicant.id == payload.applicant_id).first()
    if not applicant:
        raise HTTPException(404, detail="APPLICANT_NOT_FOUND")

    app_obj = Application(
        applicant_id=payload.applicant_id,
        requested_amount=payload.requested_amount,
        requested_term_months=payload.requested_term_months,
        product_type=payload.product_type,
        purpose=payload.purpose,
        status=ApplicationStatus.PENDING,
        kyc_step=KycStep.PERSONAL_DATA,
        kyc_started_at=datetime.now(timezone.utc),
    )
    db.add(app_obj)
    db.flush()  # get id for fk

    db.add(AuditLog(
        application_id=app_obj.id,
        step="kyc.application",
        action="CREATE_APPLICATION",
        actor=payload.applicant_id,
        actor_type="applicant",
        details={
            "amount": float(payload.requested_amount),
            "term_months": payload.requested_term_months,
            "product": payload.product_type,
        },
        ip_address=(request.client.host if request and request.client else None),
    ))
    db.commit()
    db.refresh(app_obj)
    return app_obj


@router.get("/applications", response_model=list[schemas.ApplicationOut], tags=["kyc"])
def list_applications(
    db: Session = Depends(get_db),
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    q = db.query(Application)
    if status_filter:
        q = q.filter(Application.status == status_filter)
    return q.order_by(desc(Application.created_at)).offset(offset).limit(limit).all()


@router.get("/applications/{application_id}", response_model=schemas.ApplicationOut, tags=["kyc"])
def get_application(application_id: str, db: Session = Depends(get_db)):
    a = db.query(Application).filter(Application.id == application_id).first()
    if not a:
        raise HTTPException(404, detail="APPLICATION_NOT_FOUND")
    return a


@router.post("/applications/{application_id}/decision", response_model=schemas.ApplicationOut, tags=["kyc"])
def decide_application(application_id: str, decision: schemas.ApplicationDecision, db: Session = Depends(get_db), request: Request = None):
    """Reviewer overrides ML decision."""
    a = db.query(Application).filter(Application.id == application_id).first()
    if not a:
        raise HTTPException(404, detail="APPLICATION_NOT_FOUND")

    if a.decision_at:
        raise HTTPException(409, detail="APPLICATION_ALREADY_DECIDED")

    reviewer = db.query(Reviewer).filter(Reviewer.id == decision.reviewer_id, Reviewer.is_active == True).first()
    if not reviewer:
        raise HTTPException(403, detail="REVIEWER_INVALID")

    new_status = {
        "approved": ApplicationStatus.APPROVED,
        "rejected": ApplicationStatus.REJECTED,
        "needs_more_info": ApplicationStatus.HUMAN_REVIEW,
    }.get(decision.decision)
    if not new_status:
        raise HTTPException(400, detail="INVALID_DECISION")

    a.status = new_status
    a.kyc_step = KycStep.FINAL_DECISION
    a.decision_at = datetime.now(timezone.utc)
    if a.kyc_started_at:
        a.duration_seconds = int((a.decision_at - a.kyc_started_at).total_seconds())

    db.add(AuditLog(
        application_id=a.id,
        step="kyc.decision",
        action=f"REVIEWER_{decision.decision.upper()}",
        actor=reviewer.id,
        actor_type="human",
        details={"reviewer": reviewer.username, "notes": decision.notes or ""},
    ))
    db.commit()
    db.refresh(a)
    return a


# ---------- Biometric ----------
@router.post("/biometric/verify", response_model=schemas.BiometricOut, tags=["biometric"])
def biometric_verify(payload: schemas.BiometricCaptureRequest, db: Session = Depends(get_db), request: Request = None):
    """Capture selfie + verify (quality + liveness + match)."""
    app_obj = db.query(Application).filter(Application.id == payload.application_id).first()
    if not app_obj:
        raise HTTPException(404, detail="APPLICATION_NOT_FOUND")

    # Get latest successful biometric for this app to use as reference (for match)
    prev = db.query(BiometricCheck).filter(
        BiometricCheck.application_id == payload.application_id,
        BiometricCheck.status.in_([BiometricStatus.VERIFIED, BiometricStatus.MATCH_OK]),
    ).order_by(desc(BiometricCheck.created_at)).first()
    doc_encoding = prev.face_encoding if prev else None

    result = verify_biometric(
        selfie_b64=payload.image_base64,
        document_encoding=doc_encoding,
    )

    # Persist
    if result.get("ok"):
        status_enum = BiometricStatus.VERIFIED if result.get("status") == "VERIFIED" else BiometricStatus.MATCH_FAIL
    else:
        status_map = {
            "CAPTURE_FAILED": BiometricStatus.QUALITY_FAIL,
            "QUALITY_FAIL": BiometricStatus.QUALITY_FAIL,
            "LIVENESS_FAIL": BiometricStatus.LIVENESS_FAIL,
        }
        status_enum = status_map.get(result.get("status"), BiometricStatus.QUALITY_FAIL)

    bio = BiometricCheck(
        applicant_id=app_obj.applicant_id,
        application_id=app_obj.id,
        status=status_enum,
        face_quality=result.get("face_quality"),
        face_bbox=result.get("bbox"),
        face_landmarks=result.get("landmarks"),
        liveness_passed=(result.get("liveness", {}) or {}).get("passed"),
        liveness_score=(result.get("liveness", {}) or {}).get("score"),
        liveness_method=(result.get("liveness", {}) or {}).get("method"),
        match_score=result.get("match_score"),
        match_threshold=settings.biometric_match_threshold,
        match_passed=result.get("match_passed"),
        face_encoding=result.get("encoding"),
        attempts=1,
    )
    db.add(bio)

    if status_enum == BiometricStatus.VERIFIED:
        app_obj.status = ApplicationStatus.RISK_EVALUATION
        app_obj.kyc_step = KycStep.RISK_SCORING
    elif status_enum in (BiometricStatus.LIVENESS_FAIL, BiometricStatus.MATCH_FAIL):
        app_obj.status = ApplicationStatus.HUMAN_REVIEW

    db.add(AuditLog(
        application_id=app_obj.id,
        step="kyc.biometric",
        action=f"BIOMETRIC_{status_enum.value.upper()}",
        actor=app_obj.applicant_id,
        actor_type="applicant",
        details={
            "quality": result.get("face_quality"),
            "liveness_passed": (result.get("liveness", {}) or {}).get("passed"),
            "match_passed": result.get("match_passed"),
            "match_score": result.get("match_score"),
            "errors": result.get("errors", []),
        },
        ip_address=(request.client.host if request and request.client else None),
    ))
    db.commit()
    db.refresh(bio)
    return bio


@router.get("/biometric/{application_id}", response_model=list[schemas.BiometricOut], tags=["biometric"])
def list_biometrics(application_id: str, db: Session = Depends(get_db)):
    return db.query(BiometricCheck).filter(BiometricCheck.application_id == application_id).order_by(desc(BiometricCheck.created_at)).all()


# ---------- Documents ----------
@router.post("/documents/upload/{application_id}", response_model=schemas.DocumentOut, status_code=status.HTTP_201_CREATED, tags=["kyc"])
async def upload_document(
    application_id: str,
    document_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload KYC document (INE, CURP, proof_of_address, etc)."""
    app_obj = db.query(Application).filter(Application.id == application_id).first()
    if not app_obj:
        raise HTTPException(404, detail="APPLICATION_NOT_FOUND")

    raw = await file.read()
    size = len(raw)
    if size > 8 * 1024 * 1024:
        raise HTTPException(413, detail="FILE_TOO_LARGE")
    if size < 100:
        raise HTTPException(400, detail="FILE_EMPTY")

    import hashlib
    file_hash = hashlib.sha256(raw).hexdigest()

    # Check dupe
    existing = db.query(Document).filter(
        Document.application_id == application_id,
        Document.file_hash_sha256 == file_hash,
    ).first()
    if existing:
        raise HTTPException(409, detail="DUPLICATE_DOCUMENT")

    try:
        doc_enum = DocumentType(document_type)
    except ValueError:
        raise HTTPException(400, detail=f"INVALID_DOCUMENT_TYPE: {document_type}")

    # In production: save to S3/MinIO bucket, run OCR via Textract/Google Vision
    # Here: compute deterministic OCR-style extraction from filename + size
    extracted = {
        "filename": file.filename,
        "size_bytes": size,
        "content_type": file.content_type,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    if doc_enum == DocumentType.INE_FRONT:
        extracted["nombre"] = "EXTRACTED_NAME"
        extracted["clave_elector"] = "000000ABCDEF"

    doc = Document(
        applicant_id=app_obj.applicant_id,
        application_id=app_obj.id,
        document_type=doc_enum,
        file_hash_sha256=file_hash,
        file_size_bytes=size,
        mime_type=file.content_type,
        extracted_fields=extracted,
        validation_status="auto_passed",
        validation_score=0.92,
        validation_errors=[],
        verified_at=datetime.now(timezone.utc),
    )
    db.add(doc)
    db.flush()

    db.add(AuditLog(
        application_id=app_obj.id,
        step="kyc.documents",
        action=f"DOCUMENT_UPLOADED_{doc_enum.value.upper()}",
        actor=app_obj.applicant_id,
        actor_type="applicant",
        details={"document_id": doc.id, "type": doc_enum.value, "size_bytes": size, "hash": file_hash[:12]},
    ))
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/documents/{application_id}", response_model=list[schemas.DocumentOut], tags=["kyc"])
def list_documents(application_id: str, db: Session = Depends(get_db)):
    return db.query(Document).filter(Document.application_id == application_id).order_by(desc(Document.uploaded_at)).all()


# ---------- Risk ----------
@router.post("/risk/evaluate", response_model=schemas.RiskEvaluationOut, tags=["risk"])
def evaluate_risk(payload: schemas.RiskEvaluationRequest, db: Session = Depends(get_db), request: Request = None):
    """Run ML risk scoring on the application. Sets decision if thresholds hit."""
    start = datetime.now(timezone.utc)
    app_obj = db.query(Application).filter(Application.id == payload.application_id).first()
    if not app_obj:
        raise HTTPException(404, detail="APPLICATION_NOT_FOUND")
    applicant = db.query(Applicant).filter(Applicant.id == app_obj.applicant_id).first()

    # Pull biometric
    bio = db.query(BiometricCheck).filter(
        BiometricCheck.application_id == payload.application_id,
    ).order_by(desc(BiometricCheck.created_at)).first()
    bio_dict = None
    if bio:
        bio_dict = {
            "face_quality": bio.face_quality,
            "match_passed": bio.match_passed,
            "liveness_score": bio.liveness_score,
            "liveness": {"passed": bio.liveness_passed, "score": bio.liveness_score},
        }

    # Document quality aggregate
    docs = db.query(Document).filter(Document.application_id == payload.application_id).all()
    docs_quality = 0.0
    if docs:
        docs_quality = float(sum((d.validation_score or 0.9) for d in docs) / len(docs))

    feature_dict = {
        "birth_date": str(applicant.birth_date) if applicant.birth_date else None,
        "monthly_income": float(applicant.monthly_income) if applicant.monthly_income else 0,
        "requested_amount": float(app_obj.requested_amount),
        "requested_term_months": app_obj.requested_term_months,
        "kyc_complete": 1.0 if bio and bio.status == BiometricStatus.VERIFIED else 0.0,
        "documents_quality": docs_quality,
        "bureau_score": 0.7,   # mock — in prod, fetch from Circulo de Credito
        "delinquency_history": 0,
        "open_lines": 2,
        "application_velocity_30d": 1,
        "device_repeat": 1.0,
        "geographic_consistency": 1.0,
    }

    result = score_application(feature_dict, bio_dict)

    # Persist
    app_obj.risk_score = result.score
    app_obj.risk_band = result.band
    app_obj.risk_reasons = result.reasons
    app_obj.risk_model_version = result.model_version
    app_obj.risk_features = result.features

    new_status = {
        "auto_approved": ApplicationStatus.AUTO_APPROVED,
        "auto_rejected": ApplicationStatus.AUTO_REJECTED,
        "human_review": ApplicationStatus.HUMAN_REVIEW,
    }.get(result.decision)
    if new_status:
        app_obj.status = new_status
        if new_status in (ApplicationStatus.AUTO_APPROVED, ApplicationStatus.AUTO_REJECTED):
            app_obj.decision_at = datetime.now(timezone.utc)
            if app_obj.kyc_started_at:
                app_obj.duration_seconds = int((app_obj.decision_at - app_obj.kyc_started_at).total_seconds())

    db.add(AuditLog(
        application_id=app_obj.id,
        step="kyc.risk",
        action=f"RISK_{result.decision.upper()}",
        actor="system",
        actor_type="system",
        details={
            "score": result.score,
            "band": result.band,
            "reasons": result.reasons[:5],
            "model_version": result.model_version,
        },
        ip_address=(request.client.host if request and request.client else None),
    ))
    db.commit()

    duration = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    return {
        "application_id": app_obj.id,
        "risk_score": round(result.score, 4),
        "risk_band": result.band,
        "decision": result.decision,
        "reasons": result.reasons,
        "features": {k: round(v, 4) for k, v in result.features.items()},
        "model_version": result.model_version,
        "duration_seconds": duration,
        "evaluated_at": start,
    }


@router.get("/risk/{application_id}", tags=["risk"])
def get_risk(application_id: str, db: Session = Depends(get_db)):
    a = db.query(Application).filter(Application.id == application_id).first()
    if not a:
        raise HTTPException(404, detail="APPLICATION_NOT_FOUND")
    return {
        "application_id": a.id,
        "score": a.risk_score,
        "band": a.risk_band,
        "reasons": a.risk_reasons,
        "features": a.risk_features,
        "model_version": a.risk_model_version,
        "decision": a.status.value if a.status else None,
    }


# ---------- Audit ----------
@router.get("/audit/{application_id}", tags=["system"])
def get_audit_trail(application_id: str, db: Session = Depends(get_db)):
    """Full traceability — every step logged. Used for compliance + review."""
    logs = db.query(AuditLog).filter(AuditLog.application_id == application_id).order_by(AuditLog.created_at).all()
    return [
        {
            "id": l.id,
            "step": l.step,
            "action": l.action,
            "actor": l.actor,
            "actor_type": l.actor_type,
            "details": l.details,
            "ip_address": l.ip_address,
            "created_at": l.created_at,
        }
        for l in logs
    ]
