from fastapi import APIRouter, Depends

from app.api.dependencies import require_roles
from app.api.v1.auth import auth_user_out
from app.models import User
from app.schemas.auth import AdminDashboardOut


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard", response_model=AdminDashboardOut)
def admin_dashboard(
    user: User = Depends(require_roles("ADMIN", "RECEIVER", "HANDLER")),
) -> AdminDashboardOut:
    return AdminDashboardOut(
        message="Bạn đã đăng nhập hệ thống quản trị Yên Trường 360.",
        user=auth_user_out(user),
    )


@router.get("/system")
def admin_only(user: User = Depends(require_roles("ADMIN"))) -> dict[str, str]:
    return {"role": user.role, "permission": "admin"}


@router.get("/receive-work")
def receiver_work(user: User = Depends(require_roles("ADMIN", "RECEIVER"))) -> dict[str, str]:
    return {"role": user.role, "permission": "receive"}


@router.get("/handle-work")
def handler_work(user: User = Depends(require_roles("ADMIN", "HANDLER"))) -> dict[str, str]:
    return {"role": user.role, "permission": "handle"}
