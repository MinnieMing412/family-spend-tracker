from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_PATTERN = re.compile(r"\b(?:gh[opsu]_|ya29\.)[A-Za-z0-9._-]{10,}\b")
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_ACCOUNT_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){7,18}\d(?!\d)")


def _mask_account(match: re.Match[str]) -> str:
    """Replace an account or card number with only its final four digits."""
    digits = re.sub(r"\D", "", match.group(0))
    return f"ending-{digits[-4:]}"


def redact(message: str) -> str:
    """Remove access tokens, email addresses, and account numbers from a message."""
    message = _TOKEN_PATTERN.sub("[REDACTED_TOKEN]", message)
    message = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", message)
    return _ACCOUNT_PATTERN.sub(_mask_account, message)


@dataclass(frozen=True, slots=True)
class FamilySpendError(Exception):
    """An expected CLI failure with a safe exit code and redactable message."""

    message: str
    exit_code: int = 1

    def user_message(self) -> str:
        """Return the error text after removing sensitive values."""
        return redact(self.message)
