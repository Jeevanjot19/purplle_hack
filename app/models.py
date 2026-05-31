from __future__ import annotations
import re, uuid
from datetime import datetime, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

EventType = Literal[
    "ENTRY", "EXIT", "ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL",
    "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON", "REENTRY",
]

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_NO_ZONE_TYPES      = {"ENTRY", "EXIT", "REENTRY"}
_REQUIRE_ZONE_TYPES = {"ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL"}
_INSTANT_TYPES      = {"ENTRY", "EXIT", "REENTRY", "ZONE_ENTER",
                       "BILLING_QUEUE_JOIN", "BILLING_QUEUE_ABANDON"}


class EventMetadata(BaseModel):
    queue_depth: Optional[int] = Field(None, ge=1)
    sku_zone:    Optional[str] = None
    session_seq: int           = Field(0, ge=0)
    model_config = {"extra": "ignore"}


class Event(BaseModel):
    event_id:   str             = Field(...)
    store_id:   str             = Field(..., min_length=1, max_length=50)
    camera_id:  str             = Field(..., min_length=1, max_length=50)
    visitor_id: str             = Field(..., min_length=1, max_length=50)
    event_type: EventType
    timestamp:  datetime        = Field(...)
    zone_id:    Optional[str]   = Field(None, max_length=50)
    dwell_ms:   int             = Field(0, ge=0)
    is_staff:   bool            = False
    confidence: float           = Field(..., ge=0.0, le=1.0)
    metadata:   EventMetadata   = Field(default_factory=EventMetadata)
    model_config = {"extra": "forbid"}

    @field_validator("event_id")
    @classmethod
    def validate_uuid4(cls, v: str) -> str:
        if not _UUID4_RE.match(v):
            raise ValueError(f"event_id must be a valid UUID v4, got: {v!r}")
        return v.lower()

    @field_validator("timestamp")
    @classmethod
    def validate_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        return v

    @field_validator("visitor_id")
    @classmethod
    def validate_visitor_id(cls, v: str) -> str:
        if not v.startswith("VIS_"):
            raise ValueError(f"visitor_id must start with 'VIS_', got: {v!r}")
        return v

    @model_validator(mode="after")
    def validate_zone_rules(self) -> "Event":
        et = self.event_type
        if et in _NO_ZONE_TYPES and self.zone_id is not None:
            raise ValueError(f"{et} events must have zone_id=null")
        if et in _REQUIRE_ZONE_TYPES and not self.zone_id:
            raise ValueError(f"{et} events require a non-null zone_id")
        if et == "BILLING_QUEUE_JOIN":
            if self.metadata.queue_depth is None or self.metadata.queue_depth < 1:
                raise ValueError("BILLING_QUEUE_JOIN requires metadata.queue_depth >= 1")
        if et in _INSTANT_TYPES and self.dwell_ms != 0:
            raise ValueError(f"{et} is instantaneous — dwell_ms must be 0")
        return self

    def to_db_dict(self) -> dict:
        return {
            "event_id":    self.event_id,
            "store_id":    self.store_id,
            "camera_id":   self.camera_id,
            "visitor_id":  self.visitor_id,
            "event_type":  self.event_type,
            "timestamp":   self.timestamp,
            "zone_id":     self.zone_id,
            "dwell_ms":    self.dwell_ms,
            "is_staff":    self.is_staff,
            "confidence":  self.confidence,
            "queue_depth": self.metadata.queue_depth,
            "sku_zone":    self.metadata.sku_zone,
            "session_seq": self.metadata.session_seq,
        }


class IngestPayload(BaseModel):
    events: list[Event] = Field(..., min_length=1, max_length=500)

class RejectedEvent(BaseModel):
    index:    int
    event_id: Optional[str] = None
    reason:   str
    detail:   str

class IngestResponse(BaseModel):
    accepted:          int
    rejected:          list[RejectedEvent]
    duplicate_skipped: int

def new_event_id() -> str:
    return str(uuid.uuid4())

def new_visitor_id() -> str:
    return f"VIS_{uuid.uuid4().hex[:6]}"
