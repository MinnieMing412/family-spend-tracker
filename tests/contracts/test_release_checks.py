from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from family_spend.release_checks import scan_files


class RepositoryPrivacyChecksTests(unittest.TestCase):
    def test_flags_sensitive_names_tokens_secrets_accounts_and_pdfs(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = (
                root / "credentials.json",
                root / "statement.pdf",
                root / "token-source.txt",
                root / "oauth.json",
                root / "account.txt",
            )
            paths[0].write_text("{}")
            paths[1].write_bytes(b"synthetic")
            paths[2].write_text("gho_" + "x" * 20)
            secret_key = "client_" + "secret"
            paths[3].write_text('{"' + secret_key + '":"' + "x" * 32 + '"}')
            paths[4].write_text("4111" + " 1111" * 3)

            findings = scan_files(root, paths)

        self.assertEqual(
            {
                "forbidden sensitive filename",
                "forbidden sensitive file type",
                "access token",
                "OAuth client secret",
                "full account or card number",
            },
            {finding.reason for finding in findings},
        )

    def test_allows_synthetic_masked_and_non_secret_source_content(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / "fixture.txt"
            safe.write_text(
                "ending-10005\n"
                'token = "gho_" + ("x" * 20)\n'
                'client_secret field documented without a value\n'
            )

            findings = scan_files(root, (safe,))

        self.assertEqual((), findings)


if __name__ == "__main__":
    unittest.main()
