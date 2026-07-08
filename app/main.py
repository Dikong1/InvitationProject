from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.logging_config import setup_logging

# ─── Setup logging first ─────────────────────────────────────────────────────
setup_logging(settings.LOGS_DIR)

# ─── Create media directories ─────────────────────────────────────────────────
Path(settings.MEDIA_DIR).mkdir(parents=True, exist_ok=True)
Path(settings.MEDIA_THUMBS_DIR).mkdir(parents=True, exist_ok=True)

# ─── Import routers ───────────────────────────────────────────────────────────
from app.auth.router import router as auth_router
from app.categories.router import router as categories_router
from app.inv_templates.router import router as templates_router
from app.invitations.router import router as invitations_router
from app.rsvp.router import router as rsvp_router
from app.media.router import router as media_router
from app.payments.router import router as payments_router
from app.ai.router import router as ai_router
from app.admin.router import router as admin_router

# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Invitation Platform API",
    description=(
        "Backend для платформы цифровых приглашений на казахские мероприятия. "
        "Авторизация: /auth/* | API: /api/v1/*"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS Middleware Configuration ──────────────────────────────────────────
# Define the origins that are allowed to make cross-origin requests
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    settings.FRONTEND_URL_VERCEL,
    settings.FRONTEND_URL_HOSTING,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allowed origins
    allow_credentials=True,  # Allow cookies and auth headers
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Serve uploaded media files as static files
media_root = Path("media")
media_root.mkdir(exist_ok=True)
app.mount("/media", StaticFiles(directory=str(media_root)), name="media")

# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth_router)           # /auth/*
app.include_router(categories_router)     # /api/v1/categories
app.include_router(templates_router)      # /api/v1/templates
app.include_router(invitations_router)    # /api/v1/my/invitations + /api/v1/invite/{slug}
app.include_router(rsvp_router)           # /api/v1/invite/{slug}/rsvp + guests
app.include_router(media_router)          # /api/v1/my/invitations/{id}/media
app.include_router(payments_router)       # /api/v1/payment/*
app.include_router(ai_router)             # /api/v1/ai/*
app.include_router(admin_router)          # /api/v1/admin/*


@app.get("/", tags=["health"])
async def root():
    return {"status": "ok", "message": "Invitation Platform API is running"}


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
