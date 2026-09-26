import logging
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from auth.manager import AuthManager
from auth.session import create_session, validate_session, revoke_session
from config import DATABASE_PATH

logger = logging.getLogger("reef_ai_hub.api.auth")
router = APIRouter(prefix="/api/auth", tags=["auth"])

# Standard HTTP Bearer security scheme (no query parameters)
_bearer_scheme = HTTPBearer(auto_error=False)

_auth_mgr = AuthManager(DATABASE_PATH)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=200)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class StatusResponse(BaseModel):
    authenticated: bool
    username: str | None = None


class UserInfoResponse(BaseModel):
    user_id: str
    username: str
    auth_type: str
    enabled: bool
    created_at: str | None = None
    updated_at: str | None = None
    last_login: str | None = None


def _get_user_from_credentials(credentials: HTTPAuthorizationCredentials | None) -> dict | None:
    """Validate Bearer token and return session dict, or None."""
    if not credentials:
        return None
    token = credentials.credentials
    return validate_session(token)


def require_auth(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme)) -> dict:
    """Dependency: require valid Bearer token. Returns session dict or raises 401."""
    user = _get_user_from_credentials(credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    user = await _auth_mgr.authenticate(payload.username, payload.password)
    if not user:
        logger.warning("Failed login attempt for user: %s", payload.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_session(user["username"])
    logger.info("User %s logged in", user["username"])
    return LoginResponse(access_token=token, token_type="bearer", username=user["username"])


@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme)):
    user = _get_user_from_credentials(credentials)
    if user:
        revoke_session(credentials.credentials)
        logger.info("User %s logged out", user["username"])
    return {"status": "ok"}


@router.get("/status", response_model=StatusResponse)
async def auth_status(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme)):
    user = _get_user_from_credentials(credentials)
    if user:
        return StatusResponse(authenticated=True, username=user["username"])
    return StatusResponse(authenticated=False, username=None)


@router.get("/users", response_model=list[UserInfoResponse], dependencies=[Depends(require_auth)])
async def list_users():
    users = await _auth_mgr.list_users()
    return [UserInfoResponse(**u) for u in users]


@router.post("/setup", response_model=LoginResponse)
async def setup_admin(payload: LoginRequest):
    """Create the initial admin user. Only works if no users exist."""
    existing = await _auth_mgr.list_users()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup already completed. Admin user exists.",
        )
    user = await _auth_mgr.create_user(payload.username, payload.password, auth_type="password")
    token = create_session(user["username"])
    logger.info("Initial admin user created: %s", user["username"])
    return LoginResponse(access_token=token, token_type="bearer", username=user["username"])
