"""Avatar catalogue (P1): server-side list of pickable profile pictures.

Starts empty, filled in /admin (same pattern as venues and reward rules).
``locked`` avatars exist in the catalogue (so the frontend can show them as
"coming later") but cannot be picked yet; unlocking them by coins or
achievements is parked AFTER LAUNCH (docs/TODO.md).
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Avatar:
    id: str
    image_url: str
    locked: bool = False
