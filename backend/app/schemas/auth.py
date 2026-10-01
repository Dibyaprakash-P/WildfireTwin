from __future__ import annotations

from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    confirm_password: str = Field(max_length=256)


class VerifyOtpRequest(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class EmailOnly(BaseModel):
    email: str = Field(max_length=254)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=10, max_length=8192)


class OtpStatus(BaseModel):
    status: str
    email: str
    expires_in: int
    resend_in: int
    message: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOut"
    message: str | None = None


class UserOut(BaseModel):
    id: str
    email: str
    auth_providers: list[str]
    created_at: str


TokenResponse.model_rebuild()
