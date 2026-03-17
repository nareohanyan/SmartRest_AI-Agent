from __future__ import annotations


class PersistenceError(RuntimeError):
    """Base persistence layer error."""


class PersistenceNotFoundError(PersistenceError):
    """Raised when a requested persistence entity is missing."""


class PersistenceValidationError(PersistenceError):
    """Raised when persistence input validation fails."""
