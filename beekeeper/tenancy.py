from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OrganizationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_id: str = Field(default_factory=lambda: f"org_{uuid4().hex[:12]}")
    name: str
    created_at: datetime = Field(default_factory=utcnow)


class HiveRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hive_id: str = Field(default_factory=lambda: f"hive_{uuid4().hex[:12]}")
    org_id: str
    name: str
    status: Literal["active", "paused", "archived"] = "active"
    default_honeycomb_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class HoneycombRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    honeycomb_id: str = Field(default_factory=lambda: f"comb_{uuid4().hex[:12]}")
    hive_id: str
    name: str
    root_path: str
    created_at: datetime = Field(default_factory=utcnow)


class QueenInstanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queen_id: str = Field(default_factory=lambda: f"queen_{uuid4().hex[:12]}")
    hive_id: str
    name: str
    blueprint_id: str
    status: Literal["active", "paused"] = "active"
    created_at: datetime = Field(default_factory=utcnow)


class UserRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(default_factory=lambda: f"user_{uuid4().hex[:12]}")
    email: str
    password_hash: str
    created_at: datetime = Field(default_factory=utcnow)


class UserOrgRole(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    org_id: str
    role: Literal["admin", "member", "viewer"] = "member"
    created_at: datetime = Field(default_factory=utcnow)
