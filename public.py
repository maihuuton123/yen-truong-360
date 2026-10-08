from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
import secrets

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.anti_spam import assess_public_report_submission
from app.core.config import settings
from app.core.client_metadata import collect_report_technical_metadata
from app.core.rate_limit import limit_public_lookup_requests
from app.db.dependencies import get_db
from app.models import (
    Area,
    Attachment,
    AttachmentType,
    Category,
    DuplicateLinkStatus,
    Report,
    ReportDuplicateLink,
    ReportStatus,
)
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
)
async def create_public_report(
    request: Request,
    category_id: int = Form(...),
    area_id: int = Form(...),
    description: str = Form(...),
    image: UploadFile | None = File(default=None),
    images: list[UploadFile] | None = File(default=None),
    db: Session = Depends(get_db),
) -> PublicReportCreatedOut:
    cleaned_description = validate_description(description)
    category = get_active_category(db, category_id)
    area = get_active_area(db, area_id)

    technical_metadata = collect_report_technical_metadata(request)
    spam_assessment = assess_public_report_submission(db, technical_metadata)
    technical_payload = dict(technical_metadata.technical_metadata)
    technical_payload["anti_spam"] = {
        "ip_window_count": spam_assessment.ip_window_count,
        "rapid_window_count": spam_assessment.rapid_window_count,
        "captcha_required": spam_assessment.captcha_required,
        "captcha_provider_enabled": spam_assessment.captcha_provider_enabled,
        "captcha_note": "CAPTCHA hook only; no provider is enforced unless configured.",
    }
    uploaded_images = normalized_uploads(image=image, images=images)
    attachment_data = await prepare_image_uploads(uploaded_images)

    report = Report(
        tracking_code=generate_unique_tracking_code(db),
        category_id=category.id,
        area_id=area.id,
        description=cleaned_description,
        status=ReportStatus.NEW,
        reporter_ip_hash=technical_metadata.reporter_ip_hash,
        reporter_user_agent_hash=technical_metadata.reporter_user_agent_hash,
        request_fingerprint_hash=technical_metadata.request_fingerprint_hash,
        client_submitted_at=technical_metadata.observed_at,
        technical_metadata=json.dumps(technical_payload, ensure_ascii=False),
        is_spam=spam_assessment.is_spam,
        spam_score=spam_assessment.spam_score,
        spam_reason=spam_assessment.spam_reason,
        moderation_status=spam_assessment.moderation_status,
    )
    db.add(report)
    db.flush()

    saved_file_paths: list[Path] = []
    for attachment in attachment_data:
        stored_filename, original_filename, mime_type, content = attachment
        saved_file_paths.append(save_upload_file(stored_filename, content))
        db.add(
            Attachment(
                report_id=report.id,
                stored_filename=stored_filename,
                original_filename=original_filename,
                mime_type=mime_type,
                file_size=len(content),
                attachment_type=AttachmentType.INITIAL,
                is_public=False,
            )
        )
    add_duplicate_warnings(db, report)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        cleanup_saved_files(saved_file_paths)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Không thể tạo mã tra cứu duy nhất. Vui lòng thử lại.",
        ) from exc
    except Exception:
        db.rollback()
        cleanup_saved_files(saved_file_paths)
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


def normalized_uploads(
    *,
    image: UploadFile | None,
    images: list[UploadFile] | None,
) -> list[UploadFile]:
    uploads: list[UploadFile] = []
    if image is not None:
        uploads.append(image)
    if images:
        uploads.extend(item for item in images if item is not None)

    if len(uploads) > settings.max_report_images:
        raise HTTPException(
            status_code=413,
            detail=f"Chi duoc tai len toi da {settings.max_report_images} anh cho moi phan anh.",
        )
    return uploads


async def prepare_image_uploads(images: list[UploadFile]) -> list[tuple[str, str, str, bytes]]:
    return [await prepare_image_upload(image) for image in images]


async def prepare_image_upload(image: UploadFile) -> tuple[str, str, str, bytes]:
    mime_type = image.content_type or ""
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Chỉ chấp nhận file ảnh JPG, PNG, WEBP hoặc GIF.",
        )

    raw_filename = image.filename or "upload"
    if raw_filename in {".", ".."} or any(separator in raw_filename for separator in ("/", "\\")):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Ten file anh khong hop le.",
        )
    original_filename = Path(raw_filename).name or "upload"
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
    destination = (upload_dir / stored_filename).resolve()
    upload_root = upload_dir.resolve()
    if upload_root != destination and upload_root not in destination.parents:
        raise HTTPException(status_code=422, detail="Ten file luu tru khong hop le.")
    destination.write_bytes(content)
    return destination


def cleanup_saved_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def add_duplicate_warnings(db: Session, report: Report) -> None:
    suggestions = detect_possible_duplicates(db, report)
    if not suggestions:
        return

    report.is_duplicate = True
    for candidate, score, reason in suggestions:
        db.add(
            ReportDuplicateLink(
                report_id=report.id,
                related_report_id=candidate.id,
                status=DuplicateLinkStatus.SUGGESTED,
                score=score,
                reason=reason,
            )
        )


def detect_possible_duplicates(db: Session, report: Report) -> list[tuple[Report, float, str]]:
    window_started_at = datetime.now(timezone.utc) - timedelta(hours=settings.duplicate_detection_window_hours)
    candidates = db.scalars(
        select(Report)
        .where(
            Report.id != report.id,
            Report.category_id == report.category_id,
            Report.area_id == report.area_id,
            Report.created_at >= window_started_at,
        )
        .order_by(Report.created_at.desc(), Report.id.desc())
        .limit(50)
    ).all()
    matches: list[tuple[Report, float, str]] = []
    for candidate in candidates:
        score = duplicate_score(report, candidate)
        if score >= settings.duplicate_similarity_threshold:
            matches.append((candidate, score, duplicate_reason(score)))

    matches.sort(key=lambda item: item[1], reverse=True)
    return matches[: settings.duplicate_max_suggestions]


def duplicate_score(report: Report, candidate: Report) -> float:
    score = 0.35
    score += 0.45 * jaccard_similarity(report.description, candidate.description)
    if (
        report.location_latitude is not None
        and report.location_longitude is not None
        and report.location_latitude == candidate.location_latitude
        and report.location_longitude == candidate.location_longitude
    ):
        score += 0.2
    return min(score, 1.0)


def duplicate_reason(score: float) -> str:
    return f"Cung nhom, cung khu vuc, gan thoi gian va noi dung tuong dong ({score:.2f})."


def jaccard_similarity(left: str, right: str) -> float:
    left_tokens = tokenize_for_similarity(left)
    right_tokens = tokenize_for_similarity(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def tokenize_for_similarity(value: str) -> set[str]:
    return {token for token in re.findall(r"\w+", value.lower()) if len(token) >= 3}
