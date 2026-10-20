from __future__ import annotations

import json

from typing import Any, Literal
from uuid import UUID
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

SourceID = str


class CatalogEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    event_id: UUID
    source: Literal["degreebaba-parser"]
    entity_type: Literal["university", "course", "specialization"]
    source_id: SourceID = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    version: int = Field(strict=True, ge=1, le=9_223_372_036_854_775_807)
    publication_status: Literal["publish"]
    source_url: HttpUrl = Field(max_length=2048)
    university_source_id: SourceID | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    course_source_id: SourceID | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    # Explicit, reviewed adoption of an existing row; otherwise a stable ID slug is generated.
    catalog_slug: str | None = Field(default=None, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    data: dict[str, Any]
    clear_fields: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def relationships(self):
        json.dumps(self.data, allow_nan=False)  # PostgreSQL JSONB rejects NaN/Infinity.
        if self.entity_type != "university" and not self.university_source_id:
            raise ValueError("university_source_id is required")
        if self.entity_type == "specialization" and not self.course_source_id:
            raise ValueError("course_source_id is required")
        if self.entity_type == "university" and (self.university_source_id or self.course_source_id):
            raise ValueError("university events cannot have parents")
        if self.entity_type == "course" and self.course_source_id:
            raise ValueError("course events cannot have a course parent")
        if self.source_url.username or self.source_url.password or self.source_url.scheme != "https":
            raise ValueError("source_url must be HTTPS without credentials")
        if urlsplit(str(self.source_url)).query or urlsplit(str(self.source_url)).fragment:
            raise ValueError("source_url must be a canonical URL without query or fragment")
        return self


class CatalogError(Exception):
    """Safe machine-readable error; never contains payload values or credentials."""
