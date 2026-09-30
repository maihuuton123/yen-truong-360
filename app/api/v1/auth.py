from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import bearer_scheme, get_current_user
from app.core.security import create_access_token, revoke_token, verify_password
from app.db.dependencies import get_db
from app.models import User
from app.schemas.auth import AuthTokenOut, AuthUserOut, LoginIn


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=AuthTokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)) -> AuthTokenOut:
    username = payload.username.strip()
    user = db.scalar(select(User).where(User.username == username, User.is_active.is_(True)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không đúng.",
        )

    access_token, expires_in = create_access_token(
        subject=str(user.id),
        username=user.username,
        role=user.role,
    )
    return AuthTokenOut(
        access_token=access_token,
        expires_in=expires_in,
        user=auth_user_out(user),
    )


@router.get("/me", response_model=AuthUserOut)
def me(user: User = Depends(get_current_user)) -> AuthUserOut:
    return auth_user_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    user: User = Depends(get_current_user),
) -> Response:
    _ = user
    revoke_token(credentials.credentials)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def auth_user_out(user: User) -> AuthUserOut:
    return AuthUserOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
    )
