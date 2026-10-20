"""Terms of use + privacy text (LG1').

One document per version; ``version`` is exactly the ``TERMS_VERSION`` a
server runs with and the value a player sends as ``accept_terms_version``.
The text is edited in /admin ("Terms & privacy") and shown at
``/legal/<version>``. Once any player has accepted a version it is frozen
(database trigger, migration 0020): changing the text means a new version.
"""

import re
from dataclasses import dataclass
from datetime import datetime

# Same alphabet as the public URL (/legal/<version>) and the column CHECK;
# TERMS_VERSION is at most 20 characters (users.terms_version).
LEGAL_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


@dataclass(frozen=True, slots=True)
class LegalDocument:
    version: str
    body: str
    updated_at: datetime
