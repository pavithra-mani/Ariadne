"""Operational schema: entities, links, inventory, deals, ledger, incidents, audit."""
from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")

KINDS = ("mulberry_farm", "silkworm_farm", "reeler", "spinner", "warehouse")
ROLES = tuple(k for k in KINDS if k != "warehouse")  # warehouses belong to a reeler/spinner; no separate login


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_name: Mapped[str] = mapped_column(String(120), default="")
    village: Mapped[str] = mapped_column(String(80), default="")
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    capacity_per_day: Mapped[float] = mapped_column(Float, default=0.0)  # kg/day of main product
    daily_throughput: Mapped[float] = mapped_column(Float, default=0.0)  # current kg/day
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"), nullable=True)
    serves: Mapped[str | None] = mapped_column(String(10), nullable=True)  # warehouses: reeler|spinner
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"), nullable=True)  # warehouse -> owning reeler/spinner
    area_acres: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    display_name: Mapped[str] = mapped_column(String(120), default="")


class Link(Base):
    """Supply relationship: supplier -> buyer."""
    __tablename__ = "links"
    __table_args__ = (UniqueConstraint("supplier_id", "buyer_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    share: Mapped[float] = mapped_column(Float, default=1.0)  # share of buyer's inflow


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("entity_id", "product"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    product: Mapped[str] = mapped_column(String(20))  # leaves|cocoon|yarn|thread
    on_hand: Mapped[float] = mapped_column(Float, default=0.0)
    reserved: Mapped[float] = mapped_column(Float, default=0.0)
    daily_demand: Mapped[float] = mapped_column(Float, default=0.0)
    demand_std: Mapped[float] = mapped_column(Float, default=0.0)
    lead_time_days: Mapped[float] = mapped_column(Float, default=2.0)
    shelf_life_days: Mapped[float] = mapped_column(Float, default=30.0)
    stocked_on: Mapped[date] = mapped_column(Date, default=date.today)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    is_finished: Mapped[bool] = mapped_column(Boolean, default=True)  # sellable output vs raw input


class Target(Base):
    """Spinner demand target."""
    __tablename__ = "targets"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    product: Mapped[str] = mapped_column(String(20), default="yarn")
    target_qty: Mapped[float] = mapped_column(Float)
    horizon_days: Mapped[int] = mapped_column(Integer, default=14)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(60), unique=True)
    role: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)  # "farm_id"
    kind: Mapped[str] = mapped_column(String(30), default="query")  # disease|query|low_yarn|delay|demand_surge
    is_issue: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="open")
    date: Mapped[date] = mapped_column(Date, default=date.today)
    solution: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str | None] = mapped_column(String(12), nullable=True)
    urgency: Mapped[str | None] = mapped_column(String(12), nullable=True)
    priority: Mapped[str | None] = mapped_column(String(4), nullable=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    payload: Mapped[dict] = mapped_column(JsonType, default=dict)  # finding, rag, impact, answer...
    trace: Mapped[list] = mapped_column(JsonType, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Deal(Base):
    __tablename__ = "deals"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), nullable=True, index=True)
    deal_type: Mapped[str] = mapped_column(String(40))  # farmer_reeler|reeler_spinner|farmer_farmer
    seller_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    buyer_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"), nullable=True, index=True)
    product: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float] = mapped_column(Float)
    transport_cost: Mapped[float] = mapped_column(Float, default=0.0)
    route: Mapped[dict] = mapped_column(JsonType, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|approved|rejected|executed
    seller_decision: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved|rejected
    buyer_decision: Mapped[str] = mapped_column(String(10), default="pending")
    rejected_by: Mapped[int | None] = mapped_column(ForeignKey("entities.id"), nullable=True)
    decline_reason: Mapped[str] = mapped_column(String(300), default="")
    origin: Mapped[str] = mapped_column(String(10), default="pipeline")  # pipeline (graph incident) | agent (guardian agent)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("agent_events.id"), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Ledger(Base):
    __tablename__ = "ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    product: Mapped[str] = mapped_column(String(20))
    delta_qty: Mapped[float] = mapped_column(Float, default=0.0)
    delta_money: Mapped[float] = mapped_column(Float, default=0.0)
    memo: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60))
    ref: Mapped[str] = mapped_column(String(60), default="")
    details: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), nullable=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    level: Mapped[str] = mapped_column(String(10), default="info")  # alert | warning | info | deal
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Constant(Base):
    """Last good value of a domain constant / price, with where it came from."""
    __tablename__ = "constants"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(200), default="")
    source_url: Mapped[str] = mapped_column(String(300), default="")
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentEvent(Base):
    """A change in the network that the guardian agent reacts to (also the agent's activity log)."""
    __tablename__ = "agent_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"), nullable=True, index=True)
    product: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reason: Mapped[str] = mapped_column(String(30))  # stock_changed|target_set|deal_executed|deal_rejected|incident|startup
    data: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)  # pending|running|done|error
    result: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentNote(Base):
    """A lesson the guardian agent chose to remember (read back by its recall tool and situation briefs)."""
    __tablename__ = "agent_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"), nullable=True, index=True)
    text: Mapped[str] = mapped_column(String(300))
    event_id: Mapped[int | None] = mapped_column(ForeignKey("agent_events.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
