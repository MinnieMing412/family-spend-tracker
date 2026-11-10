"""Deterministic repository privacy checks used by the release gate."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_FORBIDDEN_NAMES = frozenset(
    {
        ".env",
        "credentials.json",
        "token.json",
    }
)
_FORBIDDEN_SUFFIXES = (
    ".pdf",
    ".token.json",
    ".secret.json",
    ".extracted.txt",
)
_CONTENT_PATTERNS = (
    (
        "access token",
        re.compile(r"\b(?:gh[opsu]_|ya29\.)[A-Za-z0-9._-]{10,}\b"),
    ),
    (
        "OAuth client secret",
        re.compile(r'"(?:client_secret|refresh_token|access_token)"\s*:\s*"[^"\n]{20,}"'),
    ),
    (
        "full account or card number",
        re.compile(
            r"(?<!\d)(?:\d{16,19}|\d{4}(?:[ -]\d{4}){2,3})(?!\d)"
            r"|\b(?:account|card)(?:\s+(?:number|no\.?))?\s*[:#-]?\s*\d{7,19}\b",
            re.IGNORECASE,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class PrivacyFinding:
    """One tracked file that violates the repository privacy boundary."""

    path: Path
    reason: str


def repository_files(root: Path) -> tuple[Path, ...]:
    """Return tracked and non-ignored repository files in deterministic order."""
    result = subprocess.run(
        ("git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"),
        cwd=root,
        capture_output=True,
        check=True,
    )
    return tuple(
        root / value.decode()
        for value in sorted(item for item in result.stdout.split(b"\0") if item)
    )


def scan_files(root: Path, paths: tuple[Path, ...]) -> tuple[PrivacyFinding, ...]:
    """Inspect repository paths without emitting their sensitive contents."""
    findings: list[PrivacyFinding] = []
    for path in paths:
        relative = path.relative_to(root)
        lowered_name = path.name.casefold()
        if lowered_name in _FORBIDDEN_NAMES:
            findings.append(PrivacyFinding(relative, "forbidden sensitive filename"))
            continue
        if any(lowered_name.endswith(suffix) for suffix in _FORBIDDEN_SUFFIXES):
            findings.append(PrivacyFinding(relative, "forbidden sensitive file type"))
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for reason, pattern in _CONTENT_PATTERNS:
            if pattern.search(content):
                findings.append(PrivacyFinding(relative, reason))
    return tuple(findings)


def main(argv: list[str] | None = None) -> int:
    """Scan the current repository and print only safe path-level findings."""
    arguments = argv if argv is not None else sys.argv[1:]
    root = Path(arguments[0] if arguments else ".").resolve()
    paths = repository_files(root)
    findings = scan_files(root, paths)
    if findings:
        for finding in findings:
            print(f"privacy check failed: {finding.path}: {finding.reason}", file=sys.stderr)
        return 1
    print(f"Privacy scan passed: {len(paths)} repository files checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
