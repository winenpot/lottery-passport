import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    identifier: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    account_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unverified"
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="player")
    nickname: Mapped[str | None] = mapped_column(String(32), nullable=True)
    nickname_key: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    terms_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    home_venue_id: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("venues.id", name="fk_users_home_venue_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (Index("ix_users_identifier", "identifier"),)


class VenueModel(Base):
    __tablename__ = "venues"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    city: Mapped[str] = mapped_column(String(40), nullable=False)
    public_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AuthenticationChallengeModel(Base):
    __tablename__ = "authentication_challenges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_salt: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("ix_authentication_challenges_user_id", "user_id"),
        Index(
            "ix_authentication_challenges_expiration",
            "user_id",
            "expires_at",
            "consumed_at",
        ),
    )


class SessionModel(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_expiration", "expires_at", "revoked_at"),
    )


class PassportProgressModel(Base):
    __tablename__ = "passport_progress"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    campaign: Mapped[str] = mapped_column(String(20), nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("ix_passport_progress_user_id", "user_id"),
        UniqueConstraint(
            "user_id", "campaign", name="uq_passport_progress_user_campaign"
        ),
    )


class CodeBatchModel(Base):
    __tablename__ = "code_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    city: Mapped[str] = mapped_column(String(2), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    coins_per_code: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    format_id: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="v2-b10"
    )
    format_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    export_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    frozen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_code_batches_quantity_positive"),
        CheckConstraint(
            "coins_per_code >= 0", name="ck_code_batches_coins_non_negative"
        ),
        CheckConstraint(
            "status IN ('generated', 'active', 'void')",
            name="ck_code_batches_status",
        ),
    )


class CodeBatchEventModel(Base):
    __tablename__ = "code_batch_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("code_batches.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("ix_code_batch_events_batch_time", "batch_id", "created_at"),
        CheckConstraint(
            "event_type IN ('generated', 'exported', 'frozen', 'activated', 'voided')",
            name="ck_code_batch_events_type",
        ),
    )


class RedemptionCodeModel(Base):
    __tablename__ = "redemption_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    city: Mapped[str] = mapped_column(String(2), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    redeemed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("code_batches.id", ondelete="RESTRICT"), nullable=True
    )

    __table_args__ = (
        Index("ix_redemption_codes_city", "city"),
        Index("ix_redemption_codes_batch_id", "batch_id"),
        Index(
            "ix_redemption_codes_redeemer_time",
            "redeemed_by_user_id",
            "redeemed_at",
            postgresql_where="redeemed_by_user_id IS NOT NULL",
        ),
    )


class WalletModel(Base):
    __tablename__ = "wallets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(BigInteger, nullable=False)
    lifetime_earned: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("balance >= 0", name="ck_wallets_balance_non_negative"),
        CheckConstraint(
            "lifetime_earned >= 0", name="ck_wallets_lifetime_earned_non_negative"
        ),
    )


class CoinLedgerEntryModel(Base):
    __tablename__ = "coin_ledger_entries"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(160), unique=True, nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("amount <> 0", name="ck_coin_ledger_entries_amount_non_zero"),
        Index("ix_coin_ledger_entries_user_time", "user_id", "created_at"),
        Index("ix_coin_ledger_entries_created_at", "created_at"),
    )


class RedemptionFailureModel(Base):
    """Append-only log of CODE_INVALID outcomes, used by the per-account throttle."""

    __tablename__ = "redemption_failures"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("ix_redemption_failures_user_time", "user_id", "occurred_at"),
    )


class AuditLogModel(Base):
    """Who changed what in ``/admin``, and when. Append-only (see migration
    0012: a trigger rejects UPDATE/DELETE, like ``coin_ledger_entries``).

    Two writers: SQLAdmin's own generic CRUD audit hook (venues edits; a
    separate, best-effort transaction committed right after the edit) and
    application services with a unit of work (coin adjustments; same
    transaction as the write it covers). ``changes`` is the submitted data,
    not a before/after diff -- see app/domain/audit.py.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    entity: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "action IN ('create', 'update', 'delete')", name="ck_audit_log_action"
        ),
        Index("ix_audit_log_actor_time", "actor_user_id", "created_at"),
        Index("ix_audit_log_entity", "entity", "entity_id"),
    )
