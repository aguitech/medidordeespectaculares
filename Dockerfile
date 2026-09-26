# Medidor de Espectaculares · Multi-stage build
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps for opencv, pillow, psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps separately for layer caching
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install \
      fastapi==0.115.5 \
      "uvicorn[standard]==0.32.1" \
      sqlalchemy==2.0.36 \
      psycopg2-binary==2.9.10 \
      pydantic==2.10.3 \
      "pydantic-settings==2.7.0" \
      python-multipart==0.0.20 \
      "python-jose[cryptography]==3.3.0" \
      "passlib[bcrypt]==1.7.4" \
      numpy==2.2.0 \
      scikit-learn==1.6.0 \
      "scipy==1.14.1" \
      Pillow==11.0.0 \
      opencv-python-headless==4.10.0.84 \
      httpx==0.28.1 \
      redis==5.2.1 \
      structlog==24.4.0 \
      tenacity==9.0.0

COPY app ./app
COPY scripts ./scripts

# Run init_db on container start (idempotent — only creates admin if missing)
RUN chmod +x scripts/init_db.py

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["sh","-c","python scripts/init_db.py && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2"]
