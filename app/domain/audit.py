"""Who changed what in the admin panel, and when.

Append-only, like the coin ledger (``app/domain/ledger.py``): a correction
is a new row, never an edit; the database enforces this with a trigger.
``changes`` holds the submitted values -- SQLAdmin's own audit shape for
generic CRUD (create/update/delete on a model), or an application service's
own small summary for a custom action (a coin adjustment). It is not a full
before/after diff: SQLAdmin's CRUD hooks do not hand us the pre-edit row for
free, and for the MVP knowing who changed which row to what is enough signal.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class NewAuditEntry:
    actor_user_id: UUID
    action: AuditAction
    entity: str
    entity_id: str | None
    created_at: datetime
    changes: dict[str, Any] | None = None
    ip: str | None = None
