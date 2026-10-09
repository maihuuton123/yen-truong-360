from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.client_metadata import ReportTechnicalMetadata
from app.core.config import settings
from app.core.rate_limit import public_report_limiter, public_report_rapid_limiter
from app.models import ReportSourceBlock

SourceType = Literal["IP", "FINGERPRINT"]


@dataclass(frozen=True)
class SpamAssessment:
    is_spam: bool
    spam_score: float
    spam_reason: str | None
    moderation_status: str
    captcha_required: bool
    captcha_provider_enabled: bool
    ip_window_count: int
    rapid_window_count: int


def assess_public_report_submission(
    db: Session,
    metadata: ReportTechnicalMetadata,
) -> SpamAssessment:
    block = find_active_source_block(db, metadata)
    if block is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Nguon gui phan anh dang bi tam chan. Vui long lien he quan tri vien neu can ho tro.",
        )

    rate_key = metadata.reporter_ip_hash or metadata.request_fingerprint_hash or "unknown"
    rapid_key = metadata.request_fingerprint_hash or metadata.reporter_ip_hash or "unknown"
    ip_window_count = public_report_limiter.record(
        key=f"report:ip:{rate_key}",
        window_seconds=settings.public_report_rate_limit_window_seconds,
    )
    rapid_window_count = public_report_rapid_limiter.record(
        key=f"report:rapid:{rapid_key}",
        window_seconds=settings.public_report_rapid_window_seconds,
    )

    if ip_window_count > settings.public_report_rate_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Ban gui qua nhanh. Vui long thu lai sau.",
        )
    if rapid_window_count > settings.public_report_rapid_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Ban gui lien tuc qua nhanh. Vui long thu lai sau.",
        )

    risk_reasons: list[str] = []
    spam_score = 0.0
    if rapid_window_count >= settings.public_report_spam_flag_threshold:
        risk_reasons.append(
            f"Gui {rapid_window_count} phan anh trong {settings.public_report_rapid_window_seconds} giay."
        )
        spam_score += 0.7
    if ip_window_count >= max(settings.public_report_rate_limit - 2, settings.public_report_spam_flag_threshold):
        risk_reasons.append(
            f"Nguon IP dat {ip_window_count}/{settings.public_report_rate_limit} yeu cau trong cua so gioi han."
        )
        spam_score += 0.3

    spam_score = min(spam_score, 1.0)
    captcha_required = spam_score >= settings.public_report_captcha_risk_threshold
    is_spam = bool(risk_reasons)
    return SpamAssessment(
        is_spam=is_spam,
        spam_score=spam_score if is_spam else 0.0,
        spam_reason="; ".join(risk_reasons) if risk_reasons else None,
        moderation_status="FLAGGED" if is_spam else "UNREVIEWED",
        captcha_required=captcha_required,
        captcha_provider_enabled=settings.captcha_provider_enabled,
        ip_window_count=ip_window_count,
        rapid_window_count=rapid_window_count,
    )


def find_active_source_block(
    db: Session,
    metadata: ReportTechnicalMetadata,
) -> ReportSourceBlock | None:
    conditions = []
    if metadata.reporter_ip_hash:
        conditions.append(and_(ReportSourceBlock.source_type == "IP", ReportSourceBlock.source_hash == metadata.reporter_ip_hash))
    if metadata.request_fingerprint_hash:
        conditions.append(
            and_(
                ReportSourceBlock.source_type == "FINGERPRINT",
                ReportSourceBlock.source_hash == metadata.request_fingerprint_hash,
            )
        )
    if not conditions:
        return None

    now = datetime.now(timezone.utc)
    return db.scalar(
        select(ReportSourceBlock)
        .where(
            ReportSourceBlock.is_active.is_(True),
            or_(ReportSourceBlock.expires_at.is_(None), ReportSourceBlock.expires_at > now),
            or_(*conditions),
        )
        .order_by(ReportSourceBlock.created_at.desc(), ReportSourceBlock.id.desc())
    )


def source_hash_for_type(metadata: ReportTechnicalMetadata, source_type: SourceType) -> str | None:
    if source_type == "IP":
        return metadata.reporter_ip_hash
    return metadata.request_fingerprint_hash
