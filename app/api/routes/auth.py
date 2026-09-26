"""Reviewer auth: register (first-run only), login, JWT-protected endpoints."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import jwt, JWTError
from passlib.context import CryptContext

from app.db import get_db
from app.config import get_settings
from app.models import Reviewer
import app.schemas as schemas

router = APIRouter()
settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_token(reviewer_id: str) -> str:
    from datetime import timedelta
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": reviewer_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "type": "reviewer",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def get_current_reviewer(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Reviewer:
    if not token:
        raise HTTPException(401, detail="MISSING_TOKEN")
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        reviewer_id = payload.get("sub")
        if not reviewer_id:
            raise HTTPException(401, detail="INVALID_TOKEN")
    except JWTError:
        raise HTTPException(401, detail="INVALID_TOKEN")
    reviewer = db.query(Reviewer).filter(Reviewer.id == reviewer_id).first()
    if not reviewer or not reviewer.is_active:
        raise HTTPException(401, detail="REVIEWER_NOT_FOUND_OR_INACTIVE")
    return reviewer


@router.post("/auth/login", response_model=schemas.TokenOut, tags=["auth"])
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """OAuth2 password flow — username/password => JWT."""
    reviewer = db.query(Reviewer).filter(Reviewer.username == form.username).first()
    if not reviewer or not pwd_ctx.verify(form.password, reviewer.hashed_password):
        raise HTTPException(401, detail="BAD_CREDENTIALS")
    if not reviewer.is_active:
        raise HTTPException(403, detail="ACCOUNT_DISABLED")

    reviewer.last_login_at = datetime.now(timezone.utc)
    db.commit()

    token = create_token(reviewer.id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.jwt_expire_minutes * 60,
        "reviewer": {
            "id": reviewer.id,
            "username": reviewer.username,
            "email": reviewer.email,
            "full_name": reviewer.full_name,
            "role": reviewer.role,
            "is_active": reviewer.is_active,
            "last_login_at": reviewer.last_login_at,
        },
    }


@router.get("/auth/me", response_model=schemas.ReviewerOut, tags=["auth"])
def me(reviewer: Reviewer = Depends(get_current_reviewer)):
    return reviewer
