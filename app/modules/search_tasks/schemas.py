"""Validated contracts for manual search tasks."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class SearchTaskType(StrEnum):
    FIND_COMPANIES = "find_companies"
    ANALYZE_COMPANY = "analyze_company"


class SearchTaskStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SearchTaskCreate(BaseModel):
    original_query: Annotated[str, StringConstraints(min_length=3, max_length=4000)]
    task_type: SearchTaskType = SearchTaskType.FIND_COMPANIES
    company_name_or_url: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=1000)
    ] = None
    result_limit: int = Field(default=5, ge=1, le=20)

    @field_validator("original_query")
    @classmethod
    def original_query_must_contain_text(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("Search query must contain at least 3 visible characters")
        return value


class SearchTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    original_query: str
    query_language: str
    task_type: SearchTaskType
    parsed_country: str | None
    parsed_region: str | None
    parsed_industry: str | None
    parsed_focus: str | None
    company_name_or_url: str | None
    result_limit: int
    status: SearchTaskStatus
    current_stage: str | None
    failure_code: str | None
    failure_reason: str | None
    attempt_count: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    found_count: int
    accepted_count: int


class SearchTaskResultCreate(BaseModel):
    company_id: UUID
    accepted: bool = False
    complete_task: bool = False
