from typing import Protocol

from app.domain.legal import LegalDocument


class LegalDocuments(Protocol):
    async def get(self, version: str) -> LegalDocument | None:
        """The document for this exact version, or ``None`` if unknown."""
        ...


class LegalDocumentService:
    """Read side of the terms/privacy text (``GET /legal/{version}``).
    Writes happen only in /admin (SQLAdmin's audited CRUD)."""

    def __init__(self, documents: LegalDocuments) -> None:
        self._documents = documents

    async def get(self, version: str) -> LegalDocument | None:
        return await self._documents.get(version)
