"""Printed code batches: lifecycle, format tracking and append-only events."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.passports import CityCode


class BatchStatus(StrEnum):
    """Lifecycle of one print run of codes.

    ``generated``: codes exist in the database and in the printer file, but
    cannot be redeemed yet. Activate the batch when the product is on shelves.
    ``active``: codes can be redeemed.
    ``void``: kill switch for a leaked or misprinted batch; unredeemed codes
    stop working immediately, already-redeemed ones stay redeemed.
    """

    GENERATED = "generated"
    ACTIVE = "active"
    VOID = "void"


class BatchEventType(StrEnum):
    """One append-only history row per thing that happened to a batch.

    Recorded in ``code_batch_events`` (never updated or deleted) so a
    leaked-batch investigation or a printer dispute has a full, ordered
    trail: who did what, and when.
    """

    GENERATED = "generated"
    EXPORTED = "exported"
    FROZEN = "frozen"
    ACTIVATED = "activated"
    VOIDED = "voided"


@dataclass(slots=True)
class CodeBatch:
    id: UUID
    city: CityCode
    label: str
    quantity: int
    coins_per_code: int
    status: BatchStatus
    format_id: str
    created_at: datetime
    activated_at: datetime | None
    voided_at: datetime | None
    format_fingerprint: str | None = None
    exported_at: datetime | None = None
    export_sha256: str | None = None
    frozen_at: datetime | None = None
    pepper_fingerprint: str | None = None

    @property
    def is_frozen(self) -> bool:
        """True once the batch's format can no longer change (post-export)."""
        return self.frozen_at is not None
