import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from config import HUB_NAME, HUB_VERSION
from api.routes.server import router as server_router
from api.routes.auth import router as auth_router
from api.routes.devices import router as devices_router
from api.routes.aquawiz import router as aquawiz_router
from api.middleware.auth import AuthMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reef_ai_hub")

app = FastAPI(
    title=HUB_NAME,
    version=HUB_VERSION,
    description="Reef AI Hub — local server for aquarium monitoring and control.",
)

# CORS: allow local Flutter app connections. Restrict origins in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Phase 1A: open for local dev. Restrict in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authentication middleware - protects all routes except auth and health
app.add_middleware(AuthMiddleware)

app.include_router(server_router)
app.include_router(auth_router)
app.include_router(devices_router)
app.include_router(aquawiz_router)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    # Replace auto-generated HTTPBearer scheme name with our canonical BearerAuth
    security_schemes = openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    security_schemes["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "token",
    }
    if "HTTPBearer" in security_schemes:
        del security_schemes["HTTPBearer"]

    # Ensure every non-public operation uses BearerAuth
    public_paths = {"/health", "/docs", "/openapi.json", "/api/auth/login", "/api/auth/setup"}
    for path, methods in openapi_schema.get("paths", {}).items():
        if path in public_paths:
            continue
        for operation in methods.values():
            operation["security"] = [{"BearerAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi


@app.on_event("startup")
async def startup():
    from database.connection import init_database
    await init_database()
    logger.info("%s v%s ready", HUB_NAME, HUB_VERSION)


@app.on_event("shutdown")
async def shutdown():
    logger.info("%s shutting down", HUB_NAME)
