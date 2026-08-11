"""Versioned Google Sheets schema owned by Family Spend Tracker."""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ColumnSchema:
    """One stable machine key and its user-facing workbook header."""

    key: str
    header: str


@dataclass(frozen=True, slots=True)
class WorksheetSchema:
    """The required name and ordered columns for one worksheet."""

    name: str
    columns: tuple[ColumnSchema, ...] = ()


@dataclass(frozen=True, slots=True)
class CategorySeed:
    """One stable category ID and its initial user-facing name."""

    category_id: str
    display_name: str


def _columns(*values: tuple[str, str]) -> tuple[ColumnSchema, ...]:
    """Convert key/header pairs into immutable column definitions."""
    return tuple(ColumnSchema(key, header) for key, header in values)


WORKSHEET_SCHEMAS = (
    WorksheetSchema(
        "Transactions",
        _columns(
            ("transaction_id", "Transaction ID"),
            ("fingerprint", "Transaction Fingerprint"),
            ("statement_id", "Statement / Import ID"),
            ("institution", "Institution"),
            ("account_id", "Masked Account ID"),
            ("member_id", "Member ID"),
            ("transaction_date", "Transaction Date"),
            ("posting_date", "Posting Date"),
            ("raw_description", "Raw Description"),
            ("normalized_merchant", "Normalized Merchant"),
            ("merchant_location", "Merchant Location"),
            ("amount", "Amount"),
            ("transaction_type", "Transaction Type"),
            ("category_id", "Category"),
            ("included_in_spend", "Included in Spend"),
            ("reviewed", "User-reviewed"),
            ("imported_at", "Imported Timestamp"),
        ),
    ),
    WorksheetSchema(
        "Members",
        _columns(
            ("member_id", "Member ID"),
            ("display_name", "Display Name"),
            ("aliases", "Statement Aliases"),
            ("active", "Active"),
        ),
    ),
    WorksheetSchema(
        "Accounts",
        _columns(
            ("account_id", "Account ID"),
            ("institution", "Institution"),
            ("masked_identifier", "Masked Identifier"),
            ("default_member_id", "Default Member ID"),
            ("display_name", "Display Name"),
            ("active", "Active"),
        ),
    ),
    WorksheetSchema(
        "Categories",
        _columns(
            ("category_id", "Category ID"),
            ("display_name", "Display Name"),
            ("sort_order", "Sort Order"),
            ("active", "Active"),
        ),
    ),
    WorksheetSchema(
        "Merchant Rules",
        _columns(
            ("rule_id", "Rule ID"),
            ("match_type", "Match Type"),
            ("match_value", "Match Value"),
            ("normalized_merchant", "Normalized Merchant"),
            ("category_id", "Category ID"),
            ("priority", "Priority"),
            ("active", "Active"),
            ("updated_at", "Last Updated Timestamp"),
        ),
    ),
    WorksheetSchema(
        "Imports",
        _columns(
            ("import_id", "Import ID"),
            ("source_name", "Source Filename"),
            ("statement_hash", "Statement Hash"),
            ("institution", "Institution"),
            ("account_id", "Masked Account ID"),
            ("statement_period", "Statement Period"),
            ("reconciliation_status", "Reconciliation Status"),
            ("reconciliation_difference", "Reconciliation Difference"),
            ("override_reason", "Override Reason"),
            ("transaction_count", "Transaction Count"),
            ("status", "Import Status"),
            ("imported_at", "Imported Timestamp"),
        ),
    ),
    WorksheetSchema("Dashboard"),
)

CATEGORY_SEEDS = (
    CategorySeed("groceries", "Groceries"),
    CategorySeed("dining", "Dining"),
    CategorySeed("housing", "Housing"),
    CategorySeed("utilities", "Utilities"),
    CategorySeed("transportation", "Transportation"),
    CategorySeed("shopping", "Shopping"),
    CategorySeed("health", "Health"),
    CategorySeed("childcare", "Childcare"),
    CategorySeed("education", "Education"),
    CategorySeed("entertainment", "Entertainment"),
    CategorySeed("travel", "Travel"),
    CategorySeed("subscriptions", "Subscriptions"),
    CategorySeed("personal_care", "Personal Care"),
    CategorySeed("pets", "Pets"),
    CategorySeed("gifts_and_donations", "Gifts & Donations"),
    CategorySeed("fees", "Fees"),
    CategorySeed("cash", "Cash"),
    CategorySeed("other", "Other"),
    CategorySeed("uncategorized", "Uncategorized"),
)
