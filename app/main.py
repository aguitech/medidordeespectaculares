"""FastAPI application factory."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import get_settings
from app.db import engine, Base
from app.api.routes import main as main_routes
from app.api.routes import auth as auth_routes

settings = get_settings()
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("medidordeespectaculares")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on boot (in production, use Alembic migrations)
    log.info("Creating DB tables if needed...")
    Base.metadata.create_all(bind=engine)
    yield
    log.info("Shutting down")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "KYC + Biometria Facial + Machine Learning Risk Scoring\n\n"
        "Plataforma de originacion crediticia que automatizo identificacion, "
        "validacion biometrica, analisis de informacion y evaluacion de riesgo.\n\n"
        "**48 horas -> 11 minutos de originacion.**"
    ),
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handler
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception(f"Unhandled error on {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"error": "INTERNAL_ERROR", "detail": str(exc)[:200]},
    )


# Routers (mounted under /api)
API_PREFIX = settings.api_v1_prefix
app.include_router(main_routes.router, prefix=API_PREFIX)
app.include_router(auth_routes.router, prefix=API_PREFIX)


# Static frontend (served at / for the public site)
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        idx = STATIC_DIR / "index.html"
        if idx.exists():
            return FileResponse(str(idx))
        return {"service": settings.app_name, "api": "/api"}

    @app.get("/healthz", include_in_schema=False)
    def root_health():
        return {"service": settings.app_name, "status": "up"}
else:
    @app.get("/", tags=["system"])
    def index():
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "api_docs": "/api/docs",
            "endpoints": {
                "health": "/api/health",
                "create_applicant": "/api/applicants",
                "create_application": "/api/applications",
                "biometric_verify": "/api/biometric/verify",
                "risk_evaluate": "/api/risk/evaluate",
                "reviewer_login": "/api/auth/login",
                "audit": "/api/audit/{application_id}",
            },
        }
