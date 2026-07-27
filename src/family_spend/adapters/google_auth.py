"""Google installed-app OAuth adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

from family_spend.adapters.local import FileCredentialStore

GOOGLE_SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
GOOGLE_OPENID_SCOPE = "openid"
GOOGLE_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"


class OAuthCredentials(Protocol):
    """Serializable credentials returned by Google's installed-app flow."""

    def to_json(self) -> str:
        """Serialize credentials using Google's authorized-user format."""
        ...


class OAuthFlow(Protocol):
    """Browser-based installed application authorization flow."""

    def run_local_server(self, *, port: int, open_browser: bool) -> OAuthCredentials:
        """Open consent in a browser and receive the local redirect."""
        ...


FlowBuilder = Callable[[Path, tuple[str, ...]], OAuthFlow]
IdentityResolver = Callable[[OAuthCredentials], str]


def _build_installed_app_flow(
    client_secrets: Path,
    scopes: tuple[str, ...],
) -> OAuthFlow:
    """Build Google's installed desktop application OAuth flow."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    return cast(
        OAuthFlow,
        InstalledAppFlow.from_client_secrets_file(str(client_secrets), scopes=scopes),
    )


def _resolve_google_identity(credentials: OAuthCredentials) -> str:
    """Fetch the authenticated email through Google's OpenID user-info endpoint."""
    from google.auth.transport.requests import AuthorizedSession

    session = AuthorizedSession(cast(Any, credentials))  # type: ignore[no-untyped-call]
    response = session.get("https://openidconnect.googleapis.com/v1/userinfo", timeout=30)
    response.raise_for_status()
    identity = response.json().get("email")
    if not isinstance(identity, str) or not identity:
        raise ValueError("Google OAuth did not return an authenticated email")
    return identity


class GoogleCredentialManager:
    """Run browser OAuth and retain its result in the private credential store."""

    def __init__(
        self,
        store: FileCredentialStore,
        *,
        flow_builder: FlowBuilder = _build_installed_app_flow,
        identity_resolver: IdentityResolver = _resolve_google_identity,
    ) -> None:
        """Create the manager with an injectable browser-flow boundary."""
        self._store = store
        self._flow_builder = flow_builder
        self._identity_resolver = identity_resolver
        self._backup: dict[str, Any] | None = None
        self._authorization_in_progress = False

    def authorize(self, client_secrets: Path) -> str:
        """Stage Sheets-only credentials while retaining any previous credentials."""
        self._backup = (
            dict(self._store.load(self._store.reference)) if self._store.exists() else None
        )
        flow = self._flow_builder(
            client_secrets,
            (GOOGLE_OPENID_SCOPE, GOOGLE_EMAIL_SCOPE, GOOGLE_SHEETS_SCOPE),
        )
        credentials = flow.run_local_server(port=0, open_browser=True)
        raw = json.loads(credentials.to_json())
        if not isinstance(raw, dict):
            raise ValueError("Google OAuth returned invalid credential data")
        raw["_family_spend_identity"] = self._identity_resolver(credentials)
        self._authorization_in_progress = True
        return self._store.save(raw)

    def commit_authorization(self) -> None:
        """Accept staged credentials after workbook setup succeeds."""
        self._backup = None
        self._authorization_in_progress = False

    def rollback_authorization(self) -> None:
        """Restore previous credentials when workbook setup fails."""
        if not self._authorization_in_progress:
            return
        if self._backup is None:
            self._store.delete(self._store.reference)
        else:
            self._store.save(self._backup)
        self._backup = None
        self._authorization_in_progress = False

    def identity(self, credential_reference: str) -> str:
        """Return the authenticated email stored with the OAuth credentials."""
        identity = self._store.load(credential_reference).get("_family_spend_identity")
        if not isinstance(identity, str) or not identity:
            raise ValueError("authenticated Google identity is unavailable")
        return identity

    def delete(self, credential_reference: str) -> None:
        """Delete local OAuth credentials without touching the Google workbook."""
        self._store.delete(credential_reference)
