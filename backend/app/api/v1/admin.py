from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.dependencies import require_roles
from app.api.v1.auth import auth_user_out
from app.api.v1.public import cleanup_saved_files, normalized_uploads, prepare_image_uploads, save_upload_file
from app.core.config import settings
from app.core.qr import build_qr_svg
from app.core.security import hash_password
from app.db.dependencies import get_db
from app.models import (
    Area,
    Attachment,
    AttachmentType,
    AuditLog,
    Category,
    DuplicateLinkStatus,
    Report,
    ReportDuplicateLink,
    ReportSourceBlock,
    ReportStatus,
    StatusHistory,
    User,
)
from app.schemas.admin import (
    AdminAreaIn,
    AdminAreaOut,
    AdminAttachmentOut,
    AdminAuditLogListOut,
    AdminAuditLogOut,
    AdminCategoryIn,
    AdminCategoryOut,
    AdminDashboardOut,
    AdminMetricOut,
    AdminQrOut,
    AdminReportDetailOut,
    AdminReportDuplicateLinkIn,
    AdminReportDuplicateLinkOut,
    AdminReportListItemOut,
    AdminReportListOut,
    AdminReportSourceBlockIn,
    AdminReportSourceBlockOut,
    AdminReportTechnicalOut,
    AdminReportTransitionIn,
    AdminStatisticBucketOut,
    AdminStatisticsOut,
    AdminStatusHistoryOut,
    AdminUserCreateIn,
    AdminUserOut,
    AdminUserPasswordIn,
    AdminUserUpdateIn,
    AdminWorkSummaryOut,
)


router = APIRouter(prefix="/admin", tags=["admin"])
ADMIN_ROLES = {"ADMIN", "RECEIVER", "HANDLER"}
VIETNAM_TZ = timezone(timedelta(hours=7))


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


@router.get("/qr", response_model=AdminQrOut)
def admin_qr(
    user: User = Depends(require_roles("ADMIN")),
) -> AdminQrOut:
    _ = user
    target_url = normalized_public_site_url()
    return AdminQrOut(target_url=target_url, svg=build_qr_svg(target_url))


@router.get("/qr/download")
def download_admin_qr(
    user: User = Depends(require_roles("ADMIN")),
) -> Response:
    _ = user
    target_url = normalized_public_site_url()
    return Response(
        content=build_qr_svg(target_url),
        media_type="image/svg+xml",
        headers={
            "Content-Disposition": "attachment; filename=YenTruong360_QR.svg",
            "Cache-Control": "no-store",
        },
    )


@router.get("/statistics", response_model=AdminStatisticsOut)
def admin_statistics(
    user: User = Depends(require_roles("ADMIN", "RECEIVER", "HANDLER")),
    db: Session = Depends(get_db),
    status: ReportStatus | None = None,
    category_id: int | None = Query(default=None, ge=1),
    area_id: int | None = Query(default=None, ge=1),
    from_date: date | None = None,
    to_date: date | None = None,
) -> AdminStatisticsOut:
    _ = user
    filters = build_report_filters(
        status=status,
        category_id=category_id,
        area_id=area_id,
        from_date=from_date,
        to_date=to_date,
    )
    return build_statistics_out(db, filters)


@router.get("/statistics/export")
def export_admin_statistics_excel(
    user: User = Depends(require_roles("ADMIN", "RECEIVER", "HANDLER")),
    db: Session = Depends(get_db),
    status: ReportStatus | None = None,
    category_id: int | None = Query(default=None, ge=1),
    area_id: int | None = Query(default=None, ge=1),
    from_date: date | None = None,
    to_date: date | None = None,
) -> Response:
    _ = user
    filters = build_report_filters(
        status=status,
        category_id=category_id,
        area_id=area_id,
        from_date=from_date,
        to_date=to_date,
    )
    statement = (
        select(Report)
        .options(joinedload(Report.category), joinedload(Report.area))
        .order_by(Report.created_at.desc(), Report.id.desc())
    )
    if filters:
        statement = statement.where(*filters)

    rows = [
        [
            index,
            report.tracking_code,
            format_export_datetime(report.created_at),
            report.category.name,
            report.area.name if report.area else "Chưa xác định",
            report_status_label(report.status),
            format_export_datetime(report.updated_at),
        ]
        for index, report in enumerate(db.scalars(statement).all(), start=1)
    ]
    content = build_xlsx_bytes(
        headers=[
            "STT",
            "Mã phản ánh",
            "Ngày tiếp nhận",
            "Nhóm",
            "Khu vực",
            "Trạng thái",
            "Cập nhật gần nhất",
        ],
        rows=rows,
    )
    filename = f"YenTruong360_ThongKe_{date.today().isoformat()}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
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
    filters = build_report_filters(
        tracking_code=tracking_code,
        status=status,
        category_id=category_id,
        area_id=area_id,
        from_date=from_date,
        to_date=to_date,
    )

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


@router.get("/reports/{report_id}/technical", response_model=AdminReportTechnicalOut)
def get_report_technical_metadata(
    report_id: int,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AdminReportTechnicalOut:
    _ = user
    return report_technical_out(load_report_or_404(db, report_id), db)


@router.post("/reports/{report_id}/related-reports", response_model=AdminReportDuplicateLinkOut, status_code=status.HTTP_201_CREATED)
def link_related_report(
    report_id: int,
    payload: AdminReportDuplicateLinkIn,
    user: User = Depends(require_roles("ADMIN", "RECEIVER", "HANDLER")),
    db: Session = Depends(get_db),
) -> AdminReportDuplicateLinkOut:
    report = load_report_or_404(db, report_id)
    related = load_report_or_404(db, payload.related_report_id)
    if report.id == related.id:
        raise HTTPException(status_code=422, detail="Khong the lien ket phan anh voi chinh no.")

    existing = db.scalar(
        select(ReportDuplicateLink).where(
            or_(
                (ReportDuplicateLink.report_id == report.id)
                & (ReportDuplicateLink.related_report_id == related.id),
                (ReportDuplicateLink.report_id == related.id)
                & (ReportDuplicateLink.related_report_id == report.id),
            )
        )
    )
    if existing is None:
        link = ReportDuplicateLink(
            report_id=report.id,
            related_report_id=related.id,
            status=DuplicateLinkStatus.LINKED,
            score=None,
            reason=clean_text(payload.reason),
            created_by=user.id,
        )
        db.add(link)
        db.flush()
    else:
        link = existing
        link.status = DuplicateLinkStatus.LINKED
        link.reason = clean_text(payload.reason) or link.reason
        link.created_by = link.created_by or user.id

    report.is_duplicate = True
    related.is_duplicate = True
    db.add(
        AuditLog(
            user_id=user.id,
            action="REPORT_DUPLICATE_LINK",
            entity_type="report_duplicate_link",
            entity_id=link.id,
            details=json.dumps(
                {
                    "report_id": report.id,
                    "related_report_id": related.id,
                    "tracking_code": report.tracking_code,
                    "related_tracking_code": related.tracking_code,
                    "has_reason": bool(clean_text(payload.reason)),
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    db.refresh(link)
    return duplicate_link_out(link, report.id)


@router.post("/reports/{report_id}/source-blocks", response_model=AdminReportSourceBlockOut, status_code=status.HTTP_201_CREATED)
def block_report_source(
    report_id: int,
    payload: AdminReportSourceBlockIn,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AdminReportSourceBlockOut:
    report = load_report_or_404(db, report_id)
    source_hash = report_source_hash(report, payload.source_type)
    if not source_hash:
        raise HTTPException(status_code=422, detail="Khong co metadata phu hop de chan nguon nay.")

    now = datetime.now(timezone.utc)
    existing = db.scalar(
        select(ReportSourceBlock)
        .where(
            ReportSourceBlock.source_type == payload.source_type,
            ReportSourceBlock.source_hash == source_hash,
            ReportSourceBlock.is_active.is_(True),
            or_(ReportSourceBlock.expires_at.is_(None), ReportSourceBlock.expires_at > now),
        )
        .order_by(ReportSourceBlock.created_at.desc(), ReportSourceBlock.id.desc())
    )
    if existing is not None:
        return source_block_out(existing)

    source_block = ReportSourceBlock(
        source_type=payload.source_type,
        source_hash=source_hash,
        reason=clean_text(payload.reason),
        expires_at=payload.expires_at,
        created_by=user.id,
    )
    db.add(source_block)
    db.add(
        AuditLog(
            user_id=user.id,
            action="REPORT_SOURCE_BLOCK",
            entity_type="report_source_block",
            details=json.dumps(
                {
                    "report_id": report.id,
                    "tracking_code": report.tracking_code,
                    "source_type": payload.source_type,
                    "has_reason": bool(clean_text(payload.reason)),
                    "expires_at": payload.expires_at.isoformat() if payload.expires_at else None,
                },
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    db.refresh(source_block)
    return source_block_out(source_block)


@router.post("/source-blocks/{block_id}/unblock", response_model=AdminReportSourceBlockOut)
def unblock_report_source(
    block_id: int,
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AdminReportSourceBlockOut:
    source_block = db.get(ReportSourceBlock, block_id)
    if source_block is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Khong tim thay nguon bi chan.")
    if source_block.is_active:
        source_block.is_active = False
        source_block.lifted_at = datetime.now(timezone.utc)
        source_block.lifted_by = user.id
        db.add(
            AuditLog(
                user_id=user.id,
                action="REPORT_SOURCE_UNBLOCK",
                entity_type="report_source_block",
                entity_id=source_block.id,
                details=json.dumps(
                    {
                        "source_type": source_block.source_type,
                        "source_hash": source_block.source_hash,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
        db.refresh(source_block)
    return source_block_out(source_block)


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


@router.post("/reports/{report_id}/attachments", response_model=AdminReportDetailOut, status_code=status.HTTP_201_CREATED)
async def upload_report_processing_attachments(
    report_id: int,
    attachment_type: str = Form(...),
    images: list[UploadFile] = File(...),
    user: User = Depends(require_roles("ADMIN", "HANDLER")),
    db: Session = Depends(get_db),
) -> AdminReportDetailOut:
    report = load_report_or_404(db, report_id)
    try:
        parsed_type = AttachmentType(attachment_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Loai anh xu ly khong hop le.") from exc
    if parsed_type == AttachmentType.INITIAL:
        raise HTTPException(status_code=422, detail="API nay chi dung cho anh xu ly, khong dung cho anh ban dau.")

    uploaded_images = normalized_uploads(image=None, images=images)
    if not uploaded_images:
        raise HTTPException(status_code=422, detail="Vui long tai len it nhat mot anh xu ly.")
    attachment_data = await prepare_image_uploads(uploaded_images)
    saved_file_paths: list[Path] = []
    try:
        for stored_filename, original_filename, mime_type, content in attachment_data:
            saved_file_paths.append(save_upload_file(stored_filename, content))
            db.add(
                Attachment(
                    report_id=report.id,
                    stored_filename=stored_filename,
                    original_filename=original_filename,
                    mime_type=mime_type,
                    file_size=len(content),
                    attachment_type=parsed_type,
                    is_public=False,
                )
            )
        db.add(
            AuditLog(
                user_id=user.id,
                action="REPORT_ATTACHMENT_UPLOAD",
                entity_type="report",
                entity_id=report.id,
                details=json.dumps(
                    {
                        "tracking_code": report.tracking_code,
                        "attachment_type": parsed_type.value,
                        "count": len(attachment_data),
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        cleanup_saved_files(saved_file_paths)
        raise

    return report_detail_out(load_report_or_404(db, report.id))


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


@router.get("/audit-logs", response_model=AdminAuditLogListOut)
def list_audit_logs(
    user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
    action: str | None = Query(default=None, max_length=120),
    entity_type: str | None = Query(default=None, max_length=80),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminAuditLogListOut:
    _ = user
    filters = []
    if action:
        filters.append(AuditLog.action.ilike(f"%{action.strip()}%"))
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type.strip().lower())

    total_statement = select(func.count()).select_from(AuditLog)
    if filters:
        total_statement = total_statement.where(*filters)
    total = db.scalar(total_statement) or 0

    statement = (
        select(AuditLog)
        .options(joinedload(AuditLog.user))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    if filters:
        statement = statement.where(*filters)

    items = [audit_log_out(item) for item in db.scalars(statement).all()]
    total_pages = max(1, (total + page_size - 1) // page_size)
    return AdminAuditLogListOut(items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)


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


def normalized_public_site_url() -> str:
    target_url = settings.public_site_url.strip().rstrip("/")
    if not target_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PUBLIC_SITE_URL chua duoc cau hinh.",
        )
    if not target_url.startswith(("https://", "http://")):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PUBLIC_SITE_URL khong hop le.",
        )
    return target_url


def build_report_filters(
    *,
    tracking_code: str | None = None,
    status: ReportStatus | None = None,
    category_id: int | None = None,
    area_id: int | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list:
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
        filters.append(Report.created_at >= vietnam_day_to_utc_naive(from_date, time.min))
    if to_date:
        filters.append(Report.created_at <= vietnam_day_to_utc_naive(to_date, time.max))
    return filters


def build_statistics_out(db: Session, filters: list) -> AdminStatisticsOut:
    def count_for(status_value: ReportStatus | None = None) -> int:
        statement = select(func.count()).select_from(Report)
        if filters:
            statement = statement.where(*filters)
        if status_value:
            statement = statement.where(Report.status == status_value)
        return db.scalar(statement) or 0

    category_statement = (
        select(Category.id, Category.name, func.count(Report.id))
        .join(Report, Report.category_id == Category.id)
        .group_by(Category.id, Category.name)
        .order_by(func.count(Report.id).desc(), Category.display_order.asc(), Category.id.asc())
    )
    if filters:
        category_statement = category_statement.where(*filters)

    area_statement = (
        select(Area.id, Area.name, func.count(Report.id))
        .join(Report, Report.area_id == Area.id)
        .group_by(Area.id, Area.name)
        .order_by(func.count(Report.id).desc(), Area.display_order.asc(), Area.id.asc())
    )
    if filters:
        area_statement = area_statement.where(*filters)

    date_statement = select(Report.created_at).select_from(Report).order_by(Report.created_at.asc())
    if filters:
        date_statement = date_statement.where(*filters)
    date_counts: dict[date, int] = {}
    for created_at in db.execute(date_statement).scalars().all():
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        local_day = created_at.astimezone(VIETNAM_TZ).date()
        date_counts[local_day] = date_counts.get(local_day, 0) + 1

    return AdminStatisticsOut(
        total_reports=count_for(),
        new_reports=count_for(ReportStatus.NEW),
        received_reports=count_for(ReportStatus.RECEIVED),
        coordinating_reports=count_for(ReportStatus.COORDINATING),
        resolved_reports=count_for(ReportStatus.RESOLVED),
        out_of_scope_reports=count_for(ReportStatus.OUT_OF_SCOPE),
        by_category=[
            AdminStatisticBucketOut(key=str(category_id), label=name, value=count)
            for category_id, name, count in db.execute(category_statement).all()
        ],
        by_area=[
            AdminStatisticBucketOut(key=str(area_id), label=name, value=count)
            for area_id, name, count in db.execute(area_statement).all()
        ],
        by_date=[
            AdminStatisticBucketOut(key=day.isoformat(), label=format_statistics_day(day), value=count)
            for day, count in sorted(date_counts.items())
        ],
    )


def report_status_label(status_value: ReportStatus) -> str:
    labels = {
        ReportStatus.NEW: "Mới",
        ReportStatus.RECEIVED: "Đã tiếp nhận",
        ReportStatus.COORDINATING: "Đang phối hợp",
        ReportStatus.RESOLVED: "Đã xử lý",
        ReportStatus.OUT_OF_SCOPE: "Không thuộc phạm vi",
    }
    return labels.get(status_value, status_value.value)


def format_statistics_day(value: object) -> str:
    raw_value = str(value)
    try:
        parsed = date.fromisoformat(raw_value)
    except ValueError:
        return raw_value
    return parsed.strftime("%d/%m/%Y")


def format_export_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(VIETNAM_TZ).strftime("%d/%m/%Y %H:%M")


def vietnam_day_to_utc_naive(day: date, day_time: time) -> datetime:
    local_value = datetime.combine(day, day_time).replace(tzinfo=VIETNAM_TZ)
    return local_value.astimezone(timezone.utc).replace(tzinfo=None)


def build_xlsx_bytes(*, headers: list[str], rows: list[list[object]]) -> bytes:
    worksheet_xml = build_worksheet_xml(headers, rows)
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>""",
        )
        workbook.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>""",
        )
        workbook.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="ThongKe" sheetId="1" r:id="rId1"/></sheets></workbook>""",
        )
        workbook.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>""",
        )
        workbook.writestr(
            "xl/styles.xml",
            """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>""",
        )
        workbook.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
    return buffer.getvalue()


def build_worksheet_xml(headers: list[str], rows: list[list[object]]) -> str:
    all_rows = [headers, *rows]
    xml_rows = []
    for row_index, row in enumerate(all_rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            coordinate = f"{excel_column_name(column_index)}{row_index}"
            style = ' s="1"' if row_index == 1 else ""
            if isinstance(value, int):
                cells.append(f'<c r="{coordinate}"{style}><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{coordinate}" t="inlineStr"{style}><is><t>{escape(sanitize_excel_text(value))}</t></is></c>'
                )
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<cols><col min="1" max="1" width="8" customWidth="1"/><col min="2" max="7" width="24" customWidth="1"/></cols>'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        "</worksheet>"
    )


def excel_column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def sanitize_excel_text(value: object) -> str:
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


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


def audit_log_out(item: AuditLog) -> AdminAuditLogOut:
    return AdminAuditLogOut(
        id=item.id,
        action=item.action,
        entity_type=item.entity_type,
        entity_id=item.entity_id,
        details=redact_audit_details(item.details),
        request_id=item.request_id,
        actor_ip_hash=item.actor_ip_hash,
        actor_user_agent_hash=item.actor_user_agent_hash,
        created_at=item.created_at,
        user=auth_user_out(item.user) if item.user else None,
    )


def redact_audit_details(details: str | None) -> str | None:
    if not details:
        return details
    lowered = details.lower()
    if "password" not in lowered and "token" not in lowered and "secret" not in lowered:
        return details

    try:
        value = json.loads(details)
    except json.JSONDecodeError:
        return "[redacted]"

    def redact_value(raw: object) -> object:
        if isinstance(raw, dict):
            return {
                key: "[redacted]" if any(marker in key.lower() for marker in ("password", "token", "secret")) else redact_value(val)
                for key, val in raw.items()
            }
        if isinstance(raw, list):
            return [redact_value(item) for item in raw]
        return raw

    return json.dumps(redact_value(value), ensure_ascii=False)


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
            selectinload(Report.duplicate_links).selectinload(ReportDuplicateLink.related_report),
            selectinload(Report.related_duplicate_links).selectinload(ReportDuplicateLink.report),
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


def report_technical_out(report: Report, db: Session) -> AdminReportTechnicalOut:
    metadata: dict[str, object] | None = None
    if report.technical_metadata:
        try:
            parsed_metadata = json.loads(report.technical_metadata)
        except json.JSONDecodeError:
            parsed_metadata = None
        if isinstance(parsed_metadata, dict):
            metadata = parsed_metadata

    return AdminReportTechnicalOut(
        id=report.id,
        tracking_code=report.tracking_code,
        reporter_ip_hash=report.reporter_ip_hash,
        reporter_user_agent_hash=report.reporter_user_agent_hash,
        request_fingerprint_hash=report.request_fingerprint_hash,
        client_submitted_at=report.client_submitted_at,
        technical_metadata=metadata,
        active_source_blocks=active_source_blocks_for_report(report, db),
    )


def active_source_blocks_for_report(report: Report, db: Session) -> list[AdminReportSourceBlockOut]:
    hashes = [
        ("IP", report.reporter_ip_hash),
        ("FINGERPRINT", report.request_fingerprint_hash),
    ]
    active_blocks: list[AdminReportSourceBlockOut] = []
    now = datetime.now(timezone.utc)
    for source_type, source_hash in hashes:
        if not source_hash:
            continue
        blocks = db.scalars(
            select(ReportSourceBlock)
            .where(
                ReportSourceBlock.source_type == source_type,
                ReportSourceBlock.source_hash == source_hash,
                ReportSourceBlock.is_active.is_(True),
                or_(ReportSourceBlock.expires_at.is_(None), ReportSourceBlock.expires_at > now),
            )
            .order_by(ReportSourceBlock.created_at.desc(), ReportSourceBlock.id.desc())
        ).all()
        active_blocks.extend(source_block_out(block) for block in blocks)
    return active_blocks


def report_source_hash(report: Report, source_type: str) -> str | None:
    if source_type == "IP":
        return report.reporter_ip_hash
    if source_type == "FINGERPRINT":
        return report.request_fingerprint_hash
    return None


def source_block_out(source_block: ReportSourceBlock) -> AdminReportSourceBlockOut:
    return AdminReportSourceBlockOut(
        id=source_block.id,
        source_type=source_block.source_type,
        source_hash=source_block.source_hash,
        reason=source_block.reason,
        is_active=source_block.is_active,
        expires_at=source_block.expires_at,
        lifted_at=source_block.lifted_at,
        created_at=source_block.created_at,
        created_by=auth_user_out(source_block.created_by_user) if source_block.created_by_user else None,
        lifted_by=auth_user_out(source_block.lifted_by_user) if source_block.lifted_by_user else None,
    )


def duplicate_link_out(link: ReportDuplicateLink, current_report_id: int) -> AdminReportDuplicateLinkOut:
    related = link.related_report if link.report_id == current_report_id else link.report
    return AdminReportDuplicateLinkOut(
        id=link.id,
        report_id=link.report_id,
        related_report_id=related.id,
        related_tracking_code=related.tracking_code,
        related_status=related.status,
        status=link.status.value if hasattr(link.status, "value") else str(link.status),
        score=link.score,
        reason=link.reason,
        created_at=link.created_at,
    )


def report_detail_out(report: Report) -> AdminReportDetailOut:
    duplicate_links = [
        duplicate_link_out(link, report.id)
        for link in sorted(
            [*report.duplicate_links, *report.related_duplicate_links],
            key=lambda item: (item.status.value if hasattr(item.status, "value") else str(item.status), -(item.score or 0), item.id),
        )
    ]
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
                attachment_type=attachment.attachment_type.value
                if hasattr(attachment.attachment_type, "value")
                else str(attachment.attachment_type),
                is_public=attachment.is_public,
                created_at=attachment.created_at,
            )
            for attachment in sorted(report.attachments, key=lambda item: item.id)
        ],
        duplicate_links=duplicate_links,
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
