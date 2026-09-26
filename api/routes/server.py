import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from api.routes.auth import require_auth
from api.schemas.server import HealthResponse, ServerInfoResponse
from config import HUB_NAME, HUB_VERSION

logger = logging.getLogger("reef_ai_hub.api.server")
router = APIRouter(tags=["server"])


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(status="ok")


@router.get("/server", response_model=ServerInfoResponse, dependencies=[Depends(require_auth)])
async def server_info():
    return ServerInfoResponse(
        name=HUB_NAME,
        version=HUB_VERSION,
        status="running",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
