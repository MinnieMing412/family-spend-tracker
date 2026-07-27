from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_PATTERN = re.compile(r"\b(?:gh[opsu]_|ya29\.)[A-Za-z0-9._-]{10,}\b")
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_ACCOUNT_PATTERN = re.compile(r"\b\d{9,19}\b")


def _mask_account(match: re.Match[str]) -> str:
    return f"ending-{match.group(0)[-4:]}"


def redact(message: str) -> str:
    message = _TOKEN_PATTERN.sub("[REDACTED_TOKEN]", message)
    message = _EMAIL_PATTERN.sub("[REDACTED_EMAIL]", message)
    return _ACCOUNT_PATTERN.sub(_mask_account, message)


@dataclass(frozen=True, slots=True)
class FamilySpendError(Exception):
    message: str
    exit_code: int = 1

    def user_message(self) -> str:
        return redact(self.message)
