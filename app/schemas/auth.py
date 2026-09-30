from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
    password: str


class AuthUserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str


class AuthTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthUserOut


class AdminDashboardOut(BaseModel):
    message: str
    user: AuthUserOut
