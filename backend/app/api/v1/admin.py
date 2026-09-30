from datetime import date, datetime, time
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.dependencies import require_roles
from app.api.v1.auth import auth_user_out
from app.core.config import settings
from app.core.security import hash_password
from app.db.dependencies import get_db
from app.models import Area, Attachment, AuditLog, Category, Report, ReportStatus, StatusHistory, User
from app.schemas.admin import (
    AdminAreaIn,
    AdminAreaOut,
    AdminAttachmentOut,
    AdminCategoryIn,
    AdminCategoryOut,
    AdminDashboardOut,
    AdminMetricOut,
    AdminReportDetailOut,
    AdminReportListItemOut,
    AdminReportListOut,
    AdminReportTransitionIn,
    AdminStatusHistoryOut,
    AdminUserCreateIn,
    AdminUserOut,
    AdminUserPasswordIn,
    AdminUserUpdateIn,
    AdminWorkSummaryOut,
)


router = APIRouter(prefix="/admin", tags=["admin"])
ADMIN_ROLES = {"ADMIN", "RECEIVER", "HANDLER"}


@router.get("/dashboard", response_model=AdminDashboardOut)
def admin_dashboard(
    user: User = Depends(require_roles("ADMIN", "RECEIVER", "HANDLER")),
    db: Session = Depends(get_db),
) -> AdminDashboardOut:
    total_reports = db.scalar(select(func.count()).select_from(Report)) or 0
    new_reports = _count_status(db, ReportStatus.NEW)
    coordinating_reports = _count_status(db, ReportStatus.COORDINATING)
    resolved_reports = _count_status(db, ReportStatus.RESOLVED)
    needs_update = (
        db.scalar(
            select(func.count())
            .select_from(Report)
            .where(
                Report.status.in_([ReportStatus.RECEIVED, ReportStatus.COORDINATING]),
                or_(Report.public_response.is_(None), Report.public_response == ""),
            )
        )
        or 0
    )

    return AdminDashboardOut(
        message="Bạn đã đăng nhập hệ thống quản trị Yên Trường 360.",
        user=auth_user_out(user),
        cards=[
            AdminMetricOut(key="new", label="PHẢN ÁNH MỚI", value=new_reports),
            AdminMetricOut(key="coordinating", label="ĐANG PHỐI HỢP", value=coordinating_reports),
            AdminMetricOut(key="resolved", label="ĐÃ XỬ LÝ", value=resolved_reports),
            AdminMetricOut(key="total", label="TỔNG PHẢN ÁNH", value=total_reports),
        ],
        work=AdminWorkSummaryOut(
            new_reports=new_reports,
            coordinating_reports=coordinating_reports,
            needs_update=needs_update,
        ),
    )


@router.get("/reports", response_model=AdminReportListOut)
def list_reports(
    user: User = Depends(require_roles("ADMIN", "RECEIVER", "HANDLER")),
    db: Session = Depends(get_db),
    tracking_code: str | None = Query(default=None, max_length=40),
    status: ReportStatus | None = None,
    category_id: int | None = Query(default=None, ge=1),
    area_id: int | None = Query(default=None, ge=1),
    from_date: date | None = None,
    to_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    sort_by: str = Query(default="created_at", pattern="^(created_at|updated_at|tracking_code|status)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
) -> AdminReportListOut:
    _ = user
    filters = []
    if tracking_code:
        filters.append(Report.tracking_code.ilike(f"%{tracking_code.strip().upper()}%"))
    if status:
        filters.append(Report.status == status)
    if category_id:
        filters.append(Report.category_id == category_id)
    if area_id:
        filters.append(Report.area_id == area_id)
    if from_date:
        filters.append(Report.created_at >= datetime.combine(from_date, time.min))
    if to_date:
        filters.append(Report.created_at <= datetime.combine(to_date, time.max))

    total_statement = select(func.count()).select_from(Report)
    if filters:
        total_statement = total_statement.where(*filters)
    total = db.scalar(total_statement) or 0

    sort_column = getattr(Report, sort_by)
    order_by = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    statement = (
        select(Report)
        .options(joinedload(Report.category), joinedload(Report.area))
        .order_by(order_by, Report.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        statement = statement.where(*filters)

    reports = db.scalars(statement).all()
    items = [
        AdminReportListItemOut(
            id=report.id,
            tracking_code=report.tracking_code,
            created_at=report.created_at,
            updated_at=report.updated_at,
            category=report.category.name,
            area=report.area.name if report.area else None,
            status=report.status,
        )
        for report in reports
    ]
    total_pages = max(1, (total + page_size - 1) // page_size)
    return AdminReportListOut(items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)


@router.get("/reports/{report_id}", response_model=AdminReportDetailOut)
def get_report_detail(
    report_id: int,
    user: User = Depends(require_roles("ADMIN", "RECEIVER", "HANDLER")),
    db: Session = Depends(get_db),
) -> AdminReportDetailOut:
    _ = user
    return report_detail_out(load_report_or_404(db, report_id))


@router.get("/categories", response_model=list[AdminCategoryOut])
def list_admin_categories(
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> list[AdminCategoryOut]:
    _ = user
    categories = db.scalars(select(Category).order_by(Category.display_order, Category.id)).all()
    return [category_out(db, category) for category in categories]


@router.post("/categories", response_model=AdminCategoryOut, status_code=status.HTTP_201_CREATED)
def create_admin_category(
    payload: AdminCategoryIn,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AdminCategoryOut:
    name = require_clean_name(payload.name, "Tên nhóm phản ánh là bắt buộc.")
    category = Category(
        name=name,
        icon=clean_text(payload.icon),
        is_active=payload.is_active,
        display_order=payload.display_order,
    )
    try:
        db.add(category)
        db.flush()
        add_catalog_audit_log(
            db,
            user=user,
            action="CATEGORY_CREATE",
            entity_type="category",
            entity_id=category.id,
            before=None,
            after=catalog_snapshot(category),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tên nhóm phản ánh đã tồn tại.") from exc
    except Exception:
        db.rollback()
        raise

    return category_out(db, category)


@router.put("/categories/{category_id}", response_model=AdminCategoryOut)
def update_admin_category(
    category_id: int,
    payload: AdminCategoryIn,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AdminCategoryOut:
    category = load_category_or_404(db, category_id)
    before = catalog_snapshot(category)
    category.name = require_clean_name(payload.name, "Tên nhóm phản ánh là bắt buộc.")
    category.icon = clean_text(payload.icon)
    category.is_active = payload.is_active
    category.display_order = payload.display_order
    try:
        db.flush()
        add_catalog_audit_log(
            db,
            user=user,
            action="CATEGORY_UPDATE",
            entity_type="category",
            entity_id=category.id,
            before=before,
            after=catalog_snapshot(category),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tên nhóm phản ánh đã tồn tại.") from exc
    except Exception:
        db.rollback()
        raise

    return category_out(db, category)


@router.get("/areas", response_model=list[AdminAreaOut])
def list_admin_areas(
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> list[AdminAreaOut]:
    _ = user
    areas = db.scalars(select(Area).order_by(Area.display_order, Area.id)).all()
    return [area_out(db, area) for area in areas]


@router.post("/areas", response_model=AdminAreaOut, status_code=status.HTTP_201_CREATED)
def create_admin_area(
    payload: AdminAreaIn,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AdminAreaOut:
    name = require_clean_name(payload.name, "Tên khu vực là bắt buộc.")
    area = Area(name=name, is_active=payload.is_active, display_order=payload.display_order)
    try:
        db.add(area)
        db.flush()
        add_catalog_audit_log(
            db,
            user=user,
            action="AREA_CREATE",
            entity_type="area",
            entity_id=area.id,
            before=None,
            after=catalog_snapshot(area),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tên khu vực đã tồn tại.") from exc
    except Exception:
        db.rollback()
        raise

    return area_out(db, area)


@router.put("/areas/{area_id}", response_model=AdminAreaOut)
def update_admin_area(
    area_id: int,
    payload: AdminAreaIn,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AdminAreaOut:
    area = load_area_or_404(db, area_id)
    before = catalog_snapshot(area)
    area.name = require_clean_name(payload.name, "Tên khu vực là bắt buộc.")
    area.is_active = payload.is_active
    area.display_order = payload.display_order
    try:
        db.flush()
        add_catalog_audit_log(
            db,
            user=user,
            action="AREA_UPDATE",
            entity_type="area",
            entity_id=area.id,
            before=before,
            after=catalog_snapshot(area),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tên khu vực đã tồn tại.") from exc
    except Exception:
        db.rollback()
        raise

    return area_out(db, area)


@router.get("/users", response_model=list[AdminUserOut])
def list_admin_users(
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> list[AdminUserOut]:
    _ = user
    users = db.scalars(select(User).order_by(User.id)).all()
    return [admin_user_out(item) for item in users]


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def create_admin_user(
    payload: AdminUserCreateIn,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    username = require_clean_username(payload.username)
    full_name = require_clean_name(payload.full_name, "Tên cán bộ là bắt buộc.")
    role = require_admin_role(payload.role)
    target = User(
        username=username,
        password_hash=hash_password(payload.password),
        full_name=full_name,
        role=role,
        is_active=payload.is_active,
    )
    try:
        db.add(target)
        db.flush()
        add_user_audit_log(
            db,
            user=user,
            action="USER_CREATE",
            target=target,
            before=None,
            after=user_snapshot(target),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tên đăng nhập đã tồn tại.") from exc
    except Exception:
        db.rollback()
        raise

    return admin_user_out(target)


@router.put("/users/{user_id}", response_model=AdminUserOut)
def update_admin_user(
    user_id: int,
    payload: AdminUserUpdateIn,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    target = load_user_or_404(db, user_id)
    full_name = require_clean_name(payload.full_name, "Tên cán bộ là bắt buộc.")
    role = require_admin_role(payload.role)
    ensure_admin_account_change_is_safe(db, acting_user=user, target=target, next_role=role, next_is_active=payload.is_active)
    before = user_snapshot(target)
    target.full_name = full_name
    target.role = role
    target.is_active = payload.is_active
    try:
        db.flush()
        add_user_audit_log(
            db,
            user=user,
            action="USER_UPDATE",
            target=target,
            before=before,
            after=user_snapshot(target),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Không cập nhật được tài khoản.") from exc
    except Exception:
        db.rollback()
        raise

    return admin_user_out(target)


@router.post("/users/{user_id}/password", response_model=AdminUserOut)
def reset_admin_user_password(
    user_id: int,
    payload: AdminUserPasswordIn,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    target = load_user_or_404(db, user_id)
    before = user_snapshot(target)
    target.password_hash = hash_password(payload.password)
    try:
        db.flush()
        add_user_audit_log(
            db,
            user=user,
            action="USER_PASSWORD_RESET",
            target=target,
            before=before,
            after=user_snapshot(target),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return admin_user_out(target)


@router.get("/reports/{report_id}/attachments/{attachment_id}")
def get_report_attachment(
    report_id: int,
    attachment_id: int,
    user: User = Depends(require_roles("ADMIN", "RECEIVER", "HANDLER")),
    db: Session = Depends(get_db),
) -> FileResponse:
    _ = user
    attachment = db.scalar(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.report_id == report_id,
        )
    )
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KhÃ´ng tÃ¬m tháº¥y áº£nh Ä‘Ã­nh kÃ¨m.")

    upload_root = Path(settings.upload_dir).resolve()
    path = (upload_root / attachment.stored_filename).resolve()
    if upload_root != path and upload_root not in path.parents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File áº£nh khÃ´ng há»£p lá»‡.")
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File áº£nh khÃ´ng cÃ²n tá»“n táº¡i.")

    return FileResponse(path, media_type=attachment.mime_type, filename=attachment.original_filename)


@router.post("/reports/{report_id}/receive", response_model=AdminReportDetailOut)
def receive_report(
    report_id: int,
    payload: AdminReportTransitionIn,
    user: User = Depends(require_roles("ADMIN", "RECEIVER")),
    db: Session = Depends(get_db),
) -> AdminReportDetailOut:
    return transition_report(
        db=db,
        report_id=report_id,
        user=user,
        expected_statuses={ReportStatus.NEW},
        new_status=ReportStatus.RECEIVED,
        action="REPORT_RECEIVE",
        payload=payload,
    )


@router.post("/reports/{report_id}/coordinate", response_model=AdminReportDetailOut)
def coordinate_report(
    report_id: int,
    payload: AdminReportTransitionIn,
    user: User = Depends(require_roles("ADMIN", "RECEIVER")),
    db: Session = Depends(get_db),
) -> AdminReportDetailOut:
    return transition_report(
        db=db,
        report_id=report_id,
        user=user,
        expected_statuses={ReportStatus.RECEIVED},
        new_status=ReportStatus.COORDINATING,
        action="REPORT_COORDINATE",
        payload=payload,
    )


@router.post("/reports/{report_id}/resolve", response_model=AdminReportDetailOut)
def resolve_report(
    report_id: int,
    payload: AdminReportTransitionIn,
    user: User = Depends(require_roles("ADMIN", "HANDLER")),
    db: Session = Depends(get_db),
) -> AdminReportDetailOut:
    if not clean_text(payload.public_note):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vui lÃ²ng nháº­p káº¿t quáº£ cÃ´ng khai trÆ°á»›c khi hoÃ n thÃ nh.",
        )

    return transition_report(
        db=db,
        report_id=report_id,
        user=user,
        expected_statuses={ReportStatus.COORDINATING},
        new_status=ReportStatus.RESOLVED,
        action="REPORT_RESOLVE",
        payload=payload,
        update_public_response=True,
    )


@router.post("/reports/{report_id}/out-of-scope", response_model=AdminReportDetailOut)
def mark_report_out_of_scope(
    report_id: int,
    payload: AdminReportTransitionIn,
    user: User = Depends(require_roles("ADMIN", "RECEIVER")),
    db: Session = Depends(get_db),
) -> AdminReportDetailOut:
    return transition_report(
        db=db,
        report_id=report_id,
        user=user,
        expected_statuses={ReportStatus.NEW, ReportStatus.RECEIVED, ReportStatus.COORDINATING},
        new_status=ReportStatus.OUT_OF_SCOPE,
        action="REPORT_OUT_OF_SCOPE",
        payload=payload,
        update_public_response=bool(clean_text(payload.public_note)),
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


def _count_status(db: Session, status: ReportStatus) -> int:
    return db.scalar(select(func.count()).select_from(Report).where(Report.status == status)) or 0


def load_category_or_404(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy nhóm phản ánh.")
    return category


def load_area_or_404(db: Session, area_id: int) -> Area:
    area = db.get(Area, area_id)
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy khu vực.")
    return area


def category_out(db: Session, category: Category) -> AdminCategoryOut:
    report_count = db.scalar(select(func.count()).select_from(Report).where(Report.category_id == category.id)) or 0
    return AdminCategoryOut(
        id=category.id,
        name=category.name,
        icon=category.icon,
        is_active=category.is_active,
        display_order=category.display_order,
        report_count=report_count,
    )


def area_out(db: Session, area: Area) -> AdminAreaOut:
    report_count = db.scalar(select(func.count()).select_from(Report).where(Report.area_id == area.id)) or 0
    return AdminAreaOut(
        id=area.id,
        name=area.name,
        is_active=area.is_active,
        display_order=area.display_order,
        report_count=report_count,
    )


def load_user_or_404(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài khoản cán bộ.")
    return target


def admin_user_out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at,
    )


def require_clean_username(value: str) -> str:
    cleaned = value.strip().lower()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tên đăng nhập là bắt buộc.")
    if not cleaned.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tên đăng nhập chỉ được gồm chữ, số, dấu gạch dưới hoặc gạch ngang.",
        )
    return cleaned


def require_admin_role(value: str) -> str:
    role = value.strip().upper()
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Vai trò tài khoản không hợp lệ.")
    return role


def ensure_admin_account_change_is_safe(
    db: Session,
    *,
    acting_user: User,
    target: User,
    next_role: str,
    next_is_active: bool,
) -> None:
    if target.id == acting_user.id and (not next_is_active or next_role != "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Không thể tự khóa hoặc hạ quyền tài khoản đang đăng nhập.",
        )

    target_stops_being_active_admin = target.role == "ADMIN" and target.is_active and (
        not next_is_active or next_role != "ADMIN"
    )
    if not target_stops_being_active_admin:
        return

    active_admin_count = (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "ADMIN", User.is_active.is_(True))
        )
        or 0
    )
    if active_admin_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Không thể khóa hoặc hạ quyền ADMIN cuối cùng.",
        )


def load_report_or_404(db: Session, report_id: int) -> Report:
    report = db.scalar(
        select(Report)
        .options(
            selectinload(Report.category),
            selectinload(Report.area),
            selectinload(Report.attachments),
            selectinload(Report.status_history).selectinload(StatusHistory.changed_by_user),
        )
        .where(Report.id == report_id)
    )
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="KhÃ´ng tÃ¬m tháº¥y pháº£n Ã¡nh.")
    return report


def transition_report(
    *,
    db: Session,
    report_id: int,
    user: User,
    expected_statuses: set[ReportStatus],
    new_status: ReportStatus,
    action: str,
    payload: AdminReportTransitionIn,
    update_public_response: bool = False,
) -> AdminReportDetailOut:
    report = load_report_or_404(db, report_id)
    old_status = report.status
    if old_status not in expected_statuses:
        allowed = ", ".join(sorted(status_value.value for status_value in expected_statuses))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"KhÃ´ng thá»ƒ chuyá»ƒn tráº¡ng thÃ¡i tá»« {old_status.value} sang {new_status.value}. YÃªu cáº§u tráº¡ng thÃ¡i hiá»‡n táº¡i: {allowed}.",
        )

    internal_note = build_internal_note(payload)
    public_note = clean_text(payload.public_note)

    try:
        report.status = new_status
        if internal_note:
            report.internal_note = internal_note
        if update_public_response and public_note:
            report.public_response = public_note

        db.add(
            StatusHistory(
                report_id=report.id,
                old_status=old_status,
                new_status=new_status,
                public_note=public_note,
                internal_note=internal_note,
                changed_by=user.id,
            )
        )
        add_audit_log(
            db,
            user=user,
            action=action,
            report=report,
            old_status=old_status,
            new_status=new_status,
            payload=payload,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return report_detail_out(load_report_or_404(db, report.id))


def add_audit_log(
    db: Session,
    *,
    user: User,
    action: str,
    report: Report,
    old_status: ReportStatus,
    new_status: ReportStatus,
    payload: AdminReportTransitionIn,
) -> None:
    details = {
        "tracking_code": report.tracking_code,
        "old_status": old_status.value,
        "new_status": new_status.value,
        "has_internal_note": bool(clean_text(payload.internal_note)),
        "has_public_note": bool(clean_text(payload.public_note)),
        "coordination_target": clean_text(payload.coordination_target),
    }
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            entity_type="report",
            entity_id=report.id,
            details=json.dumps(details, ensure_ascii=False),
        )
    )


def add_catalog_audit_log(
    db: Session,
    *,
    user: User,
    action: str,
    entity_type: str,
    entity_id: int,
    before: dict[str, object] | None,
    after: dict[str, object],
) -> None:
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=json.dumps({"before": before, "after": after}, ensure_ascii=False),
        )
    )


def add_user_audit_log(
    db: Session,
    *,
    user: User,
    action: str,
    target: User,
    before: dict[str, object] | None,
    after: dict[str, object],
) -> None:
    db.add(
        AuditLog(
            user_id=user.id,
            action=action,
            entity_type="user",
            entity_id=target.id,
            details=json.dumps({"before": before, "after": after}, ensure_ascii=False),
        )
    )


def catalog_snapshot(item: Category | Area) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "id": item.id,
        "name": item.name,
        "is_active": item.is_active,
        "display_order": item.display_order,
    }
    if isinstance(item, Category):
        snapshot["icon"] = item.icon
    return snapshot


def user_snapshot(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
    }


def require_clean_name(value: str, message: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)
    return cleaned


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def build_internal_note(payload: AdminReportTransitionIn) -> str | None:
    pieces = []
    coordination_target = clean_text(payload.coordination_target)
    internal_note = clean_text(payload.internal_note)
    if coordination_target:
        pieces.append(f"Äáº§u má»‘i/bá»™ pháº­n phá»‘i há»£p: {coordination_target}")
    if internal_note:
        pieces.append(internal_note)
    return "\n".join(pieces) if pieces else None


def report_detail_out(report: Report) -> AdminReportDetailOut:
    return AdminReportDetailOut(
        id=report.id,
        tracking_code=report.tracking_code,
        created_at=report.created_at,
        updated_at=report.updated_at,
        category=report.category.name,
        area=report.area.name if report.area else None,
        description=report.description,
        status=report.status,
        public_response=report.public_response,
        internal_note=report.internal_note,
        attachments=[
            AdminAttachmentOut(
                id=attachment.id,
                original_filename=attachment.original_filename,
                mime_type=attachment.mime_type,
                file_size=attachment.file_size,
                created_at=attachment.created_at,
            )
            for attachment in sorted(report.attachments, key=lambda item: item.id)
        ],
        status_history=[
            AdminStatusHistoryOut(
                id=item.id,
                old_status=item.old_status,
                new_status=item.new_status,
                public_note=item.public_note,
                internal_note=item.internal_note,
                changed_by=auth_user_out(item.changed_by_user) if item.changed_by_user else None,
                created_at=item.created_at,
            )
            for item in sorted(report.status_history, key=lambda item: (item.created_at, item.id))
        ],
    )
