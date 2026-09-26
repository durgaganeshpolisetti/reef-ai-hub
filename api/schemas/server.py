from pydantic import BaseModel


class ServerInfoResponse(BaseModel):
    name: str
    version: str
    status: str
    timestamp: str


class HealthResponse(BaseModel):
    status: str
