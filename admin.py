from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import ReportStatus
from app.schemas.auth import AuthUserOut


class AdminMetricOut(BaseModel):
    key: str
    label: str
    value: int


class AdminWorkSummaryOut(BaseModel):
    new_reports: int
    coordinating_reports: int
    needs_update: int


class AdminDashboardOut(BaseModel):
    message: str
    user: AuthUserOut
    cards: list[AdminMetricOut]
    work: AdminWorkSummaryOut


class AdminStatisticBucketOut(BaseModel):
    key: str
    label: str
    value: int


class AdminStatisticsOut(BaseModel):
    total_reports: int
    new_reports: int
    received_reports: int
    coordinating_reports: int
    resolved_reports: int
    out_of_scope_reports: int
    by_category: list[AdminStatisticBucketOut]
    by_area: list[AdminStatisticBucketOut]
    by_date: list[AdminStatisticBucketOut]


class AdminQrOut(BaseModel):
    target_url: str
    svg: str


class AdminAuditLogOut(BaseModel):
    id: int
    action: str
    entity_type: str
    entity_id: int | None
    details: str | None
    request_id: str | None
    actor_ip_hash: str | None
    actor_user_agent_hash: str | None
    created_at: datetime
    user: AuthUserOut | None


class AdminAuditLogListOut(BaseModel):
    items: list[AdminAuditLogOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminReportListItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracking_code: str
    created_at: datetime
    updated_at: datetime
    category: str
    area: str | None
    status: ReportStatus


class AdminReportListOut(BaseModel):
    items: list[AdminReportListItemOut]
    total: int
    page: int
    page_size: int
    total_pages: int


class AdminAttachmentOut(BaseModel):
    id: int
    original_filename: str
    mime_type: str
    file_size: int
    attachment_type: str
    is_public: bool
    created_at: datetime


class AdminReportDuplicateLinkOut(BaseModel):
    id: int
    report_id: int
    related_report_id: int
    related_tracking_code: str
    related_status: ReportStatus
    status: str
    score: float | None
    reason: str | None
    created_at: datetime


class AdminStatusHistoryOut(BaseModel):
    id: int
    old_status: ReportStatus | None
    new_status: ReportStatus
    public_note: str | None
    internal_note: str | None
    changed_by: AuthUserOut | None
    created_at: datetime


class AdminReportDetailOut(BaseModel):
    id: int
    tracking_code: str
    created_at: datetime
    updated_at: datetime
    category: str
    area: str | None
    description: str
    status: ReportStatus
    public_response: str | None
    internal_note: str | None
    attachments: list[AdminAttachmentOut]
    duplicate_links: list[AdminReportDuplicateLinkOut] = Field(default_factory=list)
    status_history: list[AdminStatusHistoryOut]


class AdminReportTechnicalOut(BaseModel):
    id: int
    tracking_code: str
    reporter_ip_hash: str | None
    reporter_user_agent_hash: str | None
    request_fingerprint_hash: str | None
    client_submitted_at: datetime | None
    technical_metadata: dict[str, Any] | None
    active_source_blocks: list["AdminReportSourceBlockOut"] = Field(default_factory=list)


class AdminReportSourceBlockIn(BaseModel):
    source_type: Literal["IP", "FINGERPRINT"] = "FINGERPRINT"
    reason: str | None = Field(default=None, max_length=500)
    expires_at: datetime | None = None


class AdminReportSourceBlockOut(BaseModel):
    id: int
    source_type: str
    source_hash: str
    reason: str | None
    is_active: bool
    expires_at: datetime | None
    lifted_at: datetime | None
    created_at: datetime
    created_by: AuthUserOut | None
    lifted_by: AuthUserOut | None


class AdminReportTransitionIn(BaseModel):
    internal_note: str | None = Field(default=None, max_length=2000)
    public_note: str | None = Field(default=None, max_length=2000)
    coordination_target: str | None = Field(default=None, max_length=300)


class AdminReportDuplicateLinkIn(BaseModel):
    related_report_id: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class AdminCategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    icon: str | None = Field(default=None, max_length=80)
    is_active: bool = True
    display_order: int = Field(default=0, ge=0, le=100000)


class AdminCategoryOut(BaseModel):
    id: int
    name: str
    icon: str | None
    is_active: bool
    display_order: int
    report_count: int


class AdminAreaIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    is_active: bool = True
    display_order: int = Field(default=0, ge=0, le=100000)


class AdminAreaOut(BaseModel):
    id: int
    name: str
    is_active: bool
    display_order: int
    report_count: int


class AdminUserCreateIn(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=150)
    role: str = Field(max_length=50)
    is_active: bool = True


class AdminUserUpdateIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=150)
    role: str = Field(max_length=50)
    is_active: bool = True


class AdminUserPasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class AdminUserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime
