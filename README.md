# Medidor de Espectaculares · KYC Platform

Plataforma de originación crediticia con **KYC + Biometría Facial + Machine Learning Risk Scoring**.

> **48 horas → 11 minutos de originación.** Reducción de ~99.6% en el tiempo de originación crediticia.

---

## Stack

| Capa | Tecnología |
|---|---|
| API | FastAPI 0.115 + Pydantic v2 (Python 3.11) |
| DB | PostgreSQL 16 |
| Cache | Redis 7 |
| ML | scikit-learn + NumPy (motor rule-fusion listo para swap a modelo entrenado) |
| Biometría | OpenCV + FaceQnet-style heuristics (liveness + encoding) |
| Auth | JWT (HS256) + bcrypt |
| Deploy | Docker + EasyPanel |

---

## Estructura

```
medidordeespectaculares/
├── app/
│   ├── main.py                    # FastAPI app factory
│   ├── config.py                  # Settings (env-driven)
│   ├── db.py                      # SQLAlchemy engine
│   ├── models/__init__.py         # Applicant, Application, Document, BiometricCheck, AuditLog, Reviewer
│   ├── schemas.py                 # Pydantic request/response
│   ├── services/
│   │   ├── kyc.py                 # CURP/RFC/INE validator + business rules
│   │   ├── biometric.py           # Face encoding + liveness detection
│   │   └── risk.py                # ML risk scoring engine
│   ├── api/routes/
│   │   ├── main.py                # /api/health /applicants /applications /biometric /documents /risk /audit
│   │   └── auth.py                # /api/auth/login (JWT)
│   └── static/
│       └── index.html             # Frontend KYC multi-step (Spanish)
├── scripts/
│   └── init_db.py                 # Crea tablas + admin reviewer
├── deploy/
│   └── nginx.conf                 # Reverse proxy (si no usas EasyPanel proxy)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

---

## API Endpoints (todos bajo `/api`)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/health` | Health check (DB + Redis) |
| POST | `/applicants` | Crear solicitante (valida CURP/RFC) |
| GET | `/applicants/{id}` | Obtener solicitante |
| POST | `/applications` | Crear solicitud de crédito |
| GET | `/applications` | Listar solicitudes (con filtro `?status=`) |
| GET | `/applications/{id}` | Obtener solicitud |
| POST | `/applications/{id}/decision` | Decisión de humano (override) |
| POST | `/biometric/verify` | Captura selfie + calidad + liveness + match |
| GET | `/biometric/{application_id}` | Histórico biométrico |
| POST | `/documents/upload/{application_id}` | Subir doc (multipart) |
| GET | `/documents/{application_id}` | Listar docs |
| POST | `/risk/evaluate` | Correr motor ML risk |
| GET | `/risk/{application_id}` | Ver score guardado |
| GET | `/audit/{application_id}` | Audit trail completo |
| POST | `/auth/login` | Login JWT |
| GET | `/auth/me` | Sesión actual |

Documentación interactiva: **`https://medidordeespectaculares.com/api/docs`**

---

## Deploy en EasyPanel (paso a paso)

### 1. Crear proyecto nuevo en EasyPanel

- Dashboard → **+ New Project** → nombre `medidordeespectaculares`
- Selecciona el server donde ya tienes el dominio

### 2. Crear servicio Postgres

- **+ New Service** → **Database** → **PostgreSQL 16**
- Database name: `medidordeespectaculares`
- Username: `kyc`
- Password: genera una fuerte y **guárdala**
- Volume: persistente (default)

### 3. Crear servicio Redis (opcional, recomendado)

- **+ New Service** → **Database** → **Redis 7**
- Sin password requerida para internal use

### 4. Crear el servicio API

- **+ New Service** → **App** (Docker-based)
- Image source: **Dockerfile** (sube tu repo, o usa `docker-compose.yml`)
- Si prefieres Docker Compose, elige el template "Compose" en EasyPanel y pega tu `docker-compose.yml`

**Variables de entorno requeridas:**

```bash
DATABASE_URL=postgresql://kyc:TU_PASSWORD@postgres:5432/medidordeespectaculares
REDIS_URL=redis://redis:*** SUPER_SECRETO_RANDOM_64_CHARS
ADMIN_USERNAME=admin
ADMIN_PASSWORD=UNA_PASSWORD_FUERTE_POR_PRIMERA_VEZ
ADMIN_EMAIL=tu@email.com
ADMIN_NAME=Tu Nombre
```

**Secrets adicionales (producción real, no incluidos en este repo):**
```bash
CURP_API_URL=                 # Endpoint RENAPO/INE oficial
SAT_API_URL=                  # Endpoint SAT
BUREAU_API_URL=               # Círculo de Crédito / Buró
```

**Exposed ports:** `8000`
**Mount persistent volume** (opcional, si quieres guardar uploads locales en `/app/uploads`)

### 5. Configurar dominio

- En el servicio API → **Domain** → `medidordeespectaculares.com` y `www.medidordeespectaculares.com`
- EasyPanel automáticamente configura el reverse proxy con HTTPS vía Let's Encrypt

### 6. Primer deploy + init_db

El `CMD` del Dockerfile ya corre `init_db.py` antes de levantar uvicorn.
Esto crea las tablas y un admin inicial con las credenciales que pasaste por env.

**IMPORTANTE**: cambia el password admin en el primer login.

---

## Deploy local (para desarrollo)

```bash
# 1. Install
uv venv && source .venv/bin/activate
uv pip install -e .[dev]

# 2. Run Postgres + Redis (docker)
docker compose up -d postgres redis

# 3. Set env
export DATABASE_URL="postgresql://kyc:*** try change-me-32-chars-***
}

# 4. Init DB + run
python scripts/init_db.py
uvicorn app.main:app --reload
```

Abre `http://localhost:8000` para el frontend KYC o `http://localhost:8000/api/docs` para la API.

---

## Curl examples

### Health check
```bash
curl -s https://medidordeespectaculares.com/api/health | jq
```

### Crear solicitante
```bash
curl -s -X POST https://medidordeespectaculares.com/api/applicants \
  -H "Content-Type: application/json" \
  -d '{
    "first_name":"HECTOR",
    "last_name":"AGUILAR",
    "birth_date":"1990-02-15",
    "curp":"AAGH900215HDFRRC04",
    "email":"hector@aguitech.com",
    "phone":"+52 55 1234 5678"
  }' | jq
```

### Login reviewer
```bash
curl -s -X POST https://medidordeespectaculares.com/api/auth/login \
  -d "username=admin&password=tu_password" | jq
```

---

## Créditos

**AGUITECH · 2026** — Diseño end-to-end del pipeline KYC/Biometría/ML.
