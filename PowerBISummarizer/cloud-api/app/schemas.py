from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    created_at: datetime


class LayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    schema: str
    srid: int
    geom_type: str
