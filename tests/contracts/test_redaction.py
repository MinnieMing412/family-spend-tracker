from __future__ import annotations

import unittest

from family_spend.errors import redact


class ErrorRedactionContractTests(unittest.TestCase):
    def test_sensitive_values_are_redacted_from_user_messages(self) -> None:
        message = (
            "Google token gho_abcdefghijklmnopqrstuvwxyz012345 "
            "failed for person@example.com on account 1234567890123456"
        )

        redacted = redact(message)

        self.assertNotIn("gho_abcdefghijklmnopqrstuvwxyz012345", redacted)
        self.assertNotIn("person@example.com", redacted)
        self.assertNotIn("1234567890123456", redacted)
        self.assertIn("[REDACTED_TOKEN]", redacted)
        self.assertIn("[REDACTED_EMAIL]", redacted)
        self.assertIn("ending-3456", redacted)


if __name__ == "__main__":
    unittest.main()
