from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, String, BigInteger, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base

class EventORM(Base):
    __tablename__ = "events"
    event_id:    Mapped[str]            = mapped_column(String(36), primary_key=True)
    store_id:    Mapped[str]            = mapped_column(String(50), nullable=False)
    camera_id:   Mapped[str]            = mapped_column(String(50), nullable=False)
    visitor_id:  Mapped[str]            = mapped_column(String(50), nullable=False)
    event_type:  Mapped[str]            = mapped_column(String(30), nullable=False)
    timestamp:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), nullable=False)
    zone_id:     Mapped[Optional[str]]  = mapped_column(String(50), nullable=True)
    dwell_ms:    Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    is_staff:    Mapped[bool]           = mapped_column(Boolean, nullable=False, default=False)
    confidence:  Mapped[float]          = mapped_column(Float, nullable=False)
    queue_depth: Mapped[Optional[int]]  = mapped_column(Integer, nullable=True)
    sku_zone:    Mapped[Optional[str]]  = mapped_column(String(50), nullable=True)
    session_seq: Mapped[int]            = mapped_column(Integer, nullable=False, default=0)
    ingested_at: Mapped[datetime]       = mapped_column(DateTime(timezone=True), server_default=func.now())

class SessionORM(Base):
    __tablename__ = "sessions"
    visitor_id:      Mapped[str]             = mapped_column(String(50), primary_key=True)
    store_id:        Mapped[str]             = mapped_column(String(50), nullable=False)
    entry_time:      Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_time:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    zones_visited:   Mapped[dict]            = mapped_column(JSONB, nullable=False, default=list)
    reached_billing: Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False)
    converted:       Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False)
    basket_value:    Mapped[Optional[float]] = mapped_column(Numeric(10,2), nullable=True)
    is_staff:        Mapped[bool]            = mapped_column(Boolean, nullable=False, default=False)
    reentry_count:   Mapped[int]             = mapped_column(Integer, nullable=False, default=0)
    last_updated:    Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())

class POSTransactionORM(Base):
    __tablename__ = "pos_transactions"
    transaction_id: Mapped[str]      = mapped_column(String(50), primary_key=True)
    store_id:       Mapped[str]      = mapped_column(String(50), nullable=False)
    timestamp:      Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    basket_value:   Mapped[float]    = mapped_column(Numeric(10,2), nullable=False)

class AnomalyORM(Base):
    __tablename__ = "anomaly_log"
    id:           Mapped[int]             = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    store_id:     Mapped[str]             = mapped_column(String(50), nullable=False)
    anomaly_type: Mapped[str]             = mapped_column(String(50), nullable=False)
    severity:     Mapped[str]             = mapped_column(String(10), nullable=False)
    detected_at:  Mapped[datetime]        = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata:     Mapped[dict]            = mapped_column(JSONB, nullable=False, default=dict)
