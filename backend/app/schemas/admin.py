from datetime import datetime

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
    status_history: list[AdminStatusHistoryOut]


class AdminReportTransitionIn(BaseModel):
    internal_note: str | None = Field(default=None, max_length=2000)
    public_note: str | None = Field(default=None, max_length=2000)
    coordination_target: str | None = Field(default=None, max_length=300)
