"""PDF discovery, validation, institution detection, and parser dispatch."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pypdf import PageObject, PdfReader

from family_spend.domain.models import (
    DetectionStatus,
    Institution,
    InstitutionDetection,
    ParseResult,
)
from family_spend.errors import FamilySpendError
from family_spend.ports import ParserRegistry, StatementParser, ValidatedPdf


@dataclass(frozen=True, slots=True)
class ValidatedPdfDocument:
    """A readable, text-bearing PDF safe to pass to institution parsers."""

    path: Path
    source_name: str
    sha256: str
    page_count: int
    page_texts: tuple[str, ...]


def discover_pdfs(source: Path) -> tuple[Path, ...]:
    """Return one PDF or recursively discovered PDFs in deterministic order."""
    source = source.expanduser()
    if not source.exists():
        raise FamilySpendError(f"Statement source does not exist: {source.name}", 2)
    if source.is_file():
        if source.suffix.casefold() != ".pdf":
            raise FamilySpendError("Statement source must be a PDF file or directory", 2)
        return (source,)
    if not source.is_dir():
        raise FamilySpendError("Statement source must be a PDF file or directory", 2)

    discovered = tuple(
        sorted(
            (
                path
                for path in source.rglob("*")
                if path.is_file() and path.suffix.casefold() == ".pdf"
            ),
            key=lambda path: path.relative_to(source).as_posix().casefold(),
        )
    )
    if not discovered:
        raise FamilySpendError("No PDF statements were found in the selected directory", 2)
    return discovered


class PdfValidator:
    """Validate PDF structure and extract page text before parser dispatch."""

    def validate(self, path: Path) -> ValidatedPdfDocument:
        """Reject encrypted, corrupt, empty, or image-only documents."""
        try:
            digest = hashlib.sha256()
            with path.open("rb") as source_file:
                for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
                    digest.update(chunk)
            reader = PdfReader(path, strict=False)
            if reader.is_encrypted:
                raise FamilySpendError(
                    f"Encrypted PDF is not supported: {path.name}",
                    2,
                )
            if not reader.pages:
                raise FamilySpendError(f"PDF has no pages: {path.name}", 2)
            page_texts = tuple(self._extract_page_text(page) for page in reader.pages)
        except FamilySpendError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise FamilySpendError(f"PDF could not be read: {path.name}", 2) from error
        except Exception as error:
            raise FamilySpendError(f"PDF is corrupt or unsupported: {path.name}", 2) from error

        if not any(text.strip() for text in page_texts):
            raise FamilySpendError(
                f"PDF contains no extractable text and may be scanned: {path.name}",
                2,
            )
        return ValidatedPdfDocument(
            path=path,
            source_name=path.name,
            sha256=digest.hexdigest(),
            page_count=len(page_texts),
            page_texts=page_texts,
        )

    @staticmethod
    def _extract_page_text(page: PageObject) -> str:
        """Prefer layout extraction while remaining compatible with pypdf releases."""
        try:
            extracted = page.extract_text(extraction_mode="layout")
        except TypeError:
            extracted = page.extract_text()
        return extracted or ""


@dataclass(frozen=True, slots=True)
class ParserRegistration:
    """Stable statement markers paired with one institution parser."""

    institution: Institution
    markers: tuple[str, ...]
    parser: StatementParser
    minimum_markers: int = 2

    def __post_init__(self) -> None:
        """Require multiple markers so filenames or one phrase cannot decide."""
        if self.minimum_markers < 2 or self.minimum_markers > len(self.markers):
            raise ValueError("parser registration requires at least two usable markers")


class MarkerParserRegistry:
    """Detect parsers using multiple case-insensitive markers from page text."""

    def __init__(self, registrations: tuple[ParserRegistration, ...]) -> None:
        self._registrations = registrations

    def detect(self, source: ValidatedPdf) -> InstitutionDetection:
        """Return a structured detection result without retaining statement text."""
        candidates: list[Institution] = []
        evidence: list[str] = []
        lowered_pages = tuple(page.casefold() for page in source.page_texts)
        for registration in self._registrations:
            matches: list[str] = []
            for marker_index, marker in enumerate(registration.markers, start=1):
                for page_index, page_text in enumerate(lowered_pages, start=1):
                    if marker.casefold() in page_text:
                        matches.append(f"page-{page_index}:marker-{marker_index}")
                        break
            if len(matches) >= registration.minimum_markers:
                candidates.append(registration.institution)
                evidence.extend(matches)

        institutions = tuple(candidates)
        if not institutions:
            return InstitutionDetection(DetectionStatus.UNSUPPORTED, ())
        if len(institutions) > 1:
            return InstitutionDetection(
                DetectionStatus.AMBIGUOUS,
                institutions,
                tuple(evidence),
            )
        return InstitutionDetection(
            DetectionStatus.DETECTED,
            institutions,
            tuple(evidence),
        )

    def parser_for(self, source: ValidatedPdf) -> StatementParser:
        """Return the sole detected parser or raise an actionable safe error."""
        detection = self.detect(source)
        if detection.status is DetectionStatus.UNSUPPORTED:
            raise FamilySpendError(
                f"Unsupported statement format: {source.source_name}",
                2,
            )
        if detection.status is DetectionStatus.AMBIGUOUS:
            names = ", ".join(institution.value for institution in detection.institutions)
            raise FamilySpendError(
                f"Statement institution is ambiguous ({names}): {source.source_name}",
                2,
            )
        institution = detection.institutions[0]
        return next(
            registration.parser
            for registration in self._registrations
            if registration.institution is institution
        )


class StatementIngestionService:
    """Coordinate deterministic discovery, validation, detection, and parsing."""

    def __init__(self, validator: PdfValidator, registry: ParserRegistry) -> None:
        self._validator = validator
        self._registry = registry

    def parse(self, source: Path) -> tuple[ParseResult, ...]:
        """Parse one statement or every PDF below a directory."""
        results: list[ParseResult] = []
        for path in discover_pdfs(source):
            validated = self._validator.validate(path)
            parser = self._registry.parser_for(validated)
            results.append(parser.parse(validated))
        return tuple(results)

    def parse_summary(self, source: Path) -> str:
        """Return a user-facing summary without uploading or caching statement data."""
        results = self.parse(source)
        lines = []
        for result in results:
            statement = result.statement
            institution_name = statement.institution.value.replace("_", " ").upper()
            lines.append(
                f"Detected {institution_name} statement "
                f"{statement.source_name}: {len(statement.transactions)} transactions, "
                f"{len(statement.reported_totals)} reported totals, "
                f"{len(result.warnings)} warnings."
            )
        lines.append("Parse complete. No transactions were uploaded.")
        return "\n".join(lines)
