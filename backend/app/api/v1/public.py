from pathlib import Path
import re
import secrets

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.rate_limit import limit_public_lookup_requests, limit_public_report_requests
from app.db.dependencies import get_db
from app.models import Area, Attachment, Category, Report, ReportStatus
from app.schemas.public import (
    PublicAreaOut,
    PublicCategoryOut,
    PublicReportCreatedOut,
    PublicReportLookupOut,
    PublicReportStatusHistoryOut,
    PublicReportStatusOut,
)


router = APIRouter(prefix="/public", tags=["public"])

TRACKING_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
TRACKING_LENGTH = 6
TRACKING_CODE_PATTERN = re.compile(rf"^YT360-[{TRACKING_ALPHABET}]{{{TRACKING_LENGTH}}}$")
MAX_TRACKING_ATTEMPTS = 20
DESCRIPTION_MAX_LENGTH = 2000
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
ALLOWED_IMAGE_EXTENSIONS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
    "image/gif": {".gif"},
}
PUBLIC_STATUS_LABELS = {
    ReportStatus.NEW: "Đã tiếp nhận",
    ReportStatus.RECEIVED: "Đã tiếp nhận",
    ReportStatus.COORDINATING: "Đang phối hợp",
    ReportStatus.RESOLVED: "Đã xử lý",
    ReportStatus.OUT_OF_SCOPE: "Ngoài phạm vi tiếp nhận",
}


@router.get("/categories", response_model=list[PublicCategoryOut])
def get_public_categories(db: Session = Depends(get_db)) -> list[Category]:
    return list(
        db.scalars(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.display_order, Category.id)
        )
    )


@router.get("/areas", response_model=list[PublicAreaOut])
def get_public_areas(db: Session = Depends(get_db)) -> list[Area]:
    return list(
        db.scalars(
            select(Area)
            .where(Area.is_active.is_(True))
            .order_by(Area.display_order, Area.id)
        )
    )


@router.post(
    "/reports",
    response_model=PublicReportCreatedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_public_report_requests)],
)
async def create_public_report(
    category_id: int = Form(...),
    area_id: int = Form(...),
    description: str = Form(...),
    image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
) -> PublicReportCreatedOut:
    cleaned_description = validate_description(description)
    category = get_active_category(db, category_id)
    area = get_active_area(db, area_id)

    attachment_data = await prepare_image_upload(image) if image is not None else None

    report = Report(
        tracking_code=generate_unique_tracking_code(db),
        category_id=category.id,
        area_id=area.id,
        description=cleaned_description,
        status=ReportStatus.NEW,
    )
    db.add(report)
    db.flush()

    saved_file_path: Path | None = None
    if attachment_data is not None:
        stored_filename, original_filename, mime_type, content = attachment_data
        saved_file_path = save_upload_file(stored_filename, content)
        db.add(
            Attachment(
                report_id=report.id,
                stored_filename=stored_filename,
                original_filename=original_filename,
                mime_type=mime_type,
                file_size=len(content),
            )
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        cleanup_saved_file(saved_file_path)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Không thể tạo mã tra cứu duy nhất. Vui lòng thử lại.",
        ) from exc
    except Exception:
        db.rollback()
        cleanup_saved_file(saved_file_path)
        raise

    db.refresh(report)
    return PublicReportCreatedOut(
        tracking_code=report.tracking_code,
        created_at=report.created_at,
        status=report.status,
        message="Phản ánh đã được tiếp nhận.",
    )


@router.get(
    "/reports/{tracking_code}",
    response_model=PublicReportLookupOut,
    dependencies=[Depends(limit_public_lookup_requests)],
)
def lookup_public_report(
    tracking_code: str,
    db: Session = Depends(get_db),
) -> PublicReportLookupOut:
    cleaned_tracking_code = tracking_code.strip().upper()
    if not TRACKING_CODE_PATTERN.fullmatch(cleaned_tracking_code):
        raise HTTPException(
            status_code=422,
            detail="Mã tra cứu không hợp lệ. Vui lòng kiểm tra lại mã.",
        )

    report = db.scalar(
        select(Report)
        .options(
            selectinload(Report.category),
            selectinload(Report.area),
            selectinload(Report.status_history),
        )
        .where(Report.tracking_code == cleaned_tracking_code)
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy phản ánh với mã tra cứu này. Vui lòng kiểm tra lại mã.",
        )

    return PublicReportLookupOut(
        tracking_code=report.tracking_code,
        category=report.category.name,
        area=report.area.name if report.area else None,
        created_at=report.created_at,
        updated_at=report.updated_at,
        public_status=public_status_out(report.status),
        public_response=report.public_response,
        public_status_history=build_public_status_history(report),
    )


def public_status_out(status_value: ReportStatus) -> PublicReportStatusOut:
    return PublicReportStatusOut(
        code=status_value,
        label=PUBLIC_STATUS_LABELS[status_value],
    )


def build_public_status_history(report: Report) -> list[PublicReportStatusHistoryOut]:
    history = [
        PublicReportStatusHistoryOut(
            public_status=public_status_out(item.new_status),
            public_note=item.public_note,
            created_at=item.created_at,
        )
        for item in sorted(report.status_history, key=lambda item: (item.created_at, item.id))
    ]

    if not history:
        history.append(
            PublicReportStatusHistoryOut(
                public_status=public_status_out(report.status),
                public_note=None,
                created_at=report.created_at,
            )
        )

    return history


def validate_description(description: str) -> str:
    cleaned = description.strip()
    if not cleaned:
        raise HTTPException(
            status_code=422,
            detail="Nội dung phản ánh là bắt buộc.",
        )
    if len(cleaned) > DESCRIPTION_MAX_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Nội dung phản ánh không được vượt quá {DESCRIPTION_MAX_LENGTH} ký tự.",
        )
    return cleaned


def get_active_category(db: Session, category_id: int) -> Category:
    category = db.scalar(
        select(Category).where(Category.id == category_id, Category.is_active.is_(True))
    )
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nhóm phản ánh không hợp lệ.")
    return category


def get_active_area(db: Session, area_id: int) -> Area:
    area = db.scalar(select(Area).where(Area.id == area_id, Area.is_active.is_(True)))
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Khu vực không hợp lệ.")
    return area


def generate_tracking_code() -> str:
    token = "".join(secrets.choice(TRACKING_ALPHABET) for _ in range(TRACKING_LENGTH))
    return f"YT360-{token}"


def generate_unique_tracking_code(db: Session) -> str:
    for _ in range(MAX_TRACKING_ATTEMPTS):
        tracking_code = generate_tracking_code()
        exists = db.scalar(select(Report.id).where(Report.tracking_code == tracking_code))
        if exists is None:
            return tracking_code

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Không thể sinh mã tra cứu. Vui lòng thử lại.",
    )


async def prepare_image_upload(image: UploadFile) -> tuple[str, str, str, bytes]:
    mime_type = image.content_type or ""
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Chỉ chấp nhận file ảnh JPG, PNG, WEBP hoặc GIF.",
        )

    original_filename = Path(image.filename or "upload").name or "upload"
    original_suffix = Path(original_filename).suffix.lower()
    if original_suffix not in ALLOWED_IMAGE_EXTENSIONS[mime_type]:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Phần mở rộng file ảnh không được hỗ trợ.",
        )

    content = await image.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail="File ảnh vượt quá dung lượng cho phép.",
        )

    if not has_valid_image_signature(content, mime_type):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Nội dung file không đúng định dạng ảnh.",
        )

    stored_filename = f"{secrets.token_urlsafe(24)}{ALLOWED_IMAGE_TYPES[mime_type]}"
    return stored_filename, original_filename, mime_type, content


def has_valid_image_signature(content: bytes, mime_type: str) -> bool:
    if mime_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/gif":
        return content.startswith((b"GIF87a", b"GIF89a"))
    if mime_type == "image/webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False


def save_upload_file(stored_filename: str, content: bytes) -> Path:
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / stored_filename
    destination.write_bytes(content)
    return destination


def cleanup_saved_file(path: Path | None) -> None:
    if path is None:
        return

    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
