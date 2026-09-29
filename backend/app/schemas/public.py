from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models import ReportStatus


class PublicCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    icon: str | None
    display_order: int


class PublicAreaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_order: int


class PublicReportCreatedOut(BaseModel):
    tracking_code: str
    created_at: datetime
    status: ReportStatus
    message: str


class PublicReportStatusOut(BaseModel):
    code: ReportStatus
    label: str


class PublicReportStatusHistoryOut(BaseModel):
    public_status: PublicReportStatusOut
    public_note: str | None
    created_at: datetime


class PublicReportLookupOut(BaseModel):
    tracking_code: str
    category: str
    area: str | None
    created_at: datetime
    updated_at: datetime
    public_status: PublicReportStatusOut
    public_response: str | None
    public_status_history: list[PublicReportStatusHistoryOut]
