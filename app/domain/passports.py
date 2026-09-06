from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Campaign(StrEnum):
    PARIS = "paris"
    BERLIN = "berlin"
    PATTAYA = "pattaya"
    MEXICO = "mexico"
    MADRID = "madrid"
    TOKYO = "tokyo"
    MOSCOW = "moscow"


class CityCode(StrEnum):
    PARIS = "PR"
    BERLIN = "BE"
    PATTAYA = "PA"
    MEXICO = "ME"
    MADRID = "MA"
    TOKYO = "TO"
    MOSCOW = "MO"


@dataclass(slots=True)
class PassportProgress:
    id: UUID
    user_id: UUID
    campaign: Campaign
    points: int
    created_at: datetime
    updated_at: datetime
