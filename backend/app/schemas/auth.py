from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: Literal["patient"] = "patient"  # dentists/admins are provisioned by an administrator
    date_of_birth: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    phone: str | None = Field(default=None, max_length=32)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    full_name: str
    email: EmailStr
    role: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class ProfileOut(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    role: str
    phone: str | None = None
    date_of_birth: str | None = None


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    date_of_birth: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")
