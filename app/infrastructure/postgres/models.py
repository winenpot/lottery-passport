import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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
    # A real city (tehran/ahvaz/...), never a flavor; validated by the
    # application against SUPPORTED_CITY_IDS, like venues.city.
    location_city: Mapped[str | None] = mapped_column(String(40), nullable=True)
    avatar_id: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("avatars.id", name="fk_users_avatar_id", ondelete="SET NULL"),
        nullable=True,
    )
    # RF1: generated lazily on first read (ReferralService.ensure_code), not
    # backfilled by migration 0019 for pre-existing users.
    referral_code: Mapped[str | None] = mapped_column(
        String(8), unique=True, nullable=True
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


class AvatarModel(Base):
    """Avatar catalogue (P1). Starts empty, filled in /admin; ``locked``
    avatars are shown but cannot be picked until an unlock exists."""

    __tablename__ = "avatars"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    unlock_rule: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sort: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class TeamMembershipModel(Base):
    """Flavor team history (app/domain/teams.py). The current team is the
    row with the highest ``switch_no``; UNIQUE (user_id, switch_no) makes two
    concurrent joins of one player fail instead of both landing."""

    __tablename__ = "team_memberships"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    flavor: Mapped[str] = mapped_column(String(2), nullable=False)
    switch_no: Mapped[int] = mapped_column(Integer, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "switch_no", name="uq_team_memberships_user_switch"
        ),
        CheckConstraint("switch_no >= 0", name="ck_team_memberships_switch_no"),
        CheckConstraint(
            "flavor IN ('PR', 'BE', 'PA', 'ME', 'MA', 'TO', 'MO')",
            name="ck_team_memberships_flavor",
        ),
    )


class ReferralModel(Base):
    """One row per invitee (RF1): PK on ``invitee_user_id`` makes "one
    inviter per user, bound once" a database guarantee, not just an
    application check -- the same pattern as ``team_memberships``' switch
    guard and ``mini_game_runs``' one-open-run index."""

    __tablename__ = "referrals"

    invitee_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    inviter_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "invitee_user_id <> inviter_user_id", name="ck_referrals_no_self"
        ),
        Index("ix_referrals_inviter", "inviter_user_id"),
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
    # Pepper guard (app.application.redemption_codes): which pepper signed
    # this batch. NULL = generated before the guard existed (never flagged).
    pepper_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

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
    asset: Mapped[str] = mapped_column(String(20), nullable=False, default="coin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("amount <> 0", name="ck_coin_ledger_entries_amount_non_zero"),
        CheckConstraint(
            "asset = 'coin'", name="ck_coin_ledger_entries_asset_coin_only"
        ),
        Index("ix_coin_ledger_entries_user_time", "user_id", "created_at"),
        Index("ix_coin_ledger_entries_created_at", "created_at"),
    )


class RewardRuleModel(Base):
    """Admin-tunable reward amounts (ADR 0010). No rows seeded by migration;
    a missing key means "use the service's configured default"."""

    __tablename__ = "reward_rules"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    cadence: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_reward_rules_amount_positive"),
        CheckConstraint(
            "cadence IN ('once', 'daily', 'weekly', 'monthly')",
            name="ck_reward_rules_cadence",
        ),
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


class ChallengeModel(Base):
    """Admin-tunable challenge catalogue (C1): starts empty, filled in
    ``/admin``, same pattern as ``avatars``/``reward_rules``. ``kind`` is
    the closed set app/domain/challenges.py knows how to check progress
    for; ``target``/``reward_coins``/``active`` are Mehdi's to tune."""

    __tablename__ = "challenges"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    target: Mapped[int] = mapped_column(Integer, nullable=False)
    reward_coins: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("target > 0", name="ck_challenges_target_positive"),
        CheckConstraint(
            "reward_coins >= 0", name="ck_challenges_reward_coins_non_negative"
        ),
        CheckConstraint(
            "kind IN ('team_choice', 'distinct_flavors', 'daily_checkin')",
            name="ck_challenges_kind",
        ),
        CheckConstraint(
            "period IN ('once', 'day', 'week', 'month')", name="ck_challenges_period"
        ),
    )


class ChallengeClaimModel(Base):
    """One row per user per challenge per period claimed (C1). The unique
    constraint is the idempotent-claim guard, the same shape as
    ``team_memberships``' ``switch_no`` guard; it is what actually stops a
    double pay under concurrency, not the caller's own checks."""

    __tablename__ = "challenge_claims"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    challenge_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("challenges.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    period_key: Mapped[str] = mapped_column(String(20), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "challenge_id",
            "user_id",
            "period_key",
            name="uq_challenge_claims_challenge_user_period",
        ),
        Index("ix_challenge_claims_user", "user_id"),
    )


class AchievementModel(Base):
    """Admin-tunable achievement catalogue (AC1 MVP slice): starts empty,
    filled in ``/admin``, same pattern as ``challenges``/avatars/
    reward_rules. ``fact`` is the closed set app/domain/achievements.py
    knows how to check a player's progress against."""

    __tablename__ = "achievements"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    fact: Mapped[str] = mapped_column(String(30), nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    reward_coins: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint("threshold > 0", name="ck_achievements_threshold_positive"),
        CheckConstraint(
            "reward_coins >= 0", name="ck_achievements_reward_coins_non_negative"
        ),
        CheckConstraint("fact IN ('checkin_streak')", name="ck_achievements_fact"),
    )


class MiniGameRunModel(Base):
    """One server-issued, server-verified Tap Reflex run (G1).

    Our own in-app reaction mini-game, not the physical arcade machines at
    the OxinGame lounges (docs/GLOSSARY.md) -- hence "mini game" throughout,
    not "game". ``round_delays_ms`` is the exact array handed to the client
    at issue time; re-checking it against the client's reported reactions
    and the server's own wall clock at finish time is what makes the game
    plausibility-checkable (app/domain/mini_games.py). The partial unique
    index ``uq_mini_game_runs_user_open`` (migration 0017) enforces "one
    open run per user" as a database guarantee, not just an application
    check.
    """

    __tablename__ = "mini_game_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    mini_game_id: Mapped[str] = mapped_column(String(20), nullable=False)
    round_delays_ms: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    average_reaction_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "mini_game_id IN ('tap_reflex')", name="ck_mini_game_runs_mini_game_id"
        ),
        CheckConstraint(
            "status IN ('open', 'accepted', 'rejected', 'expired')",
            name="ck_mini_game_runs_status",
        ),
        Index(
            "uq_mini_game_runs_user_open",
            "user_id",
            unique=True,
            postgresql_where="status = 'open'",
        ),
        Index("ix_mini_game_runs_user_status", "user_id", "status"),
    )


class UserAchievementModel(Base):
    """One row per player per achievement ever unlocked (AC1). The unique
    constraint is the only-once guard, the same shape as
    ``challenge_claims``; there is no claim step -- unlocking IS the pay."""

    __tablename__ = "user_achievements"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    achievement_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("achievements.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "achievement_id", "user_id", name="uq_user_achievements_achievement_user"
        ),
        Index("ix_user_achievements_user", "user_id"),
    )
