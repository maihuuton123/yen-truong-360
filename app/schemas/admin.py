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
