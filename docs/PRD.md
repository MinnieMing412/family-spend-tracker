# Family Spend Tracker - Product Requirements Document

**Status:** Finalized for v1
**Date:** 2026-07-26
**Product surface:** macOS command-line interface and Google Sheets workbook
**CLI command:** `family-spend`

## 1. Product summary

Family Spend Tracker is a privacy-conscious CLI tool for importing family bank and credit-card statement PDFs into a normalized Google Sheets ledger. It parses supported statements, assigns each transaction to the correct family member, applies learned merchant categorization rules, requires human review where needed, prevents duplicate imports, and maintains an automatically updated spending dashboard.

The first release supports text-based, English-language, USD statements from:

- American Express
- Bank of America
- Chase

One trusted household administrator operates the CLI on macOS. Other family members are represented in the workbook but do not need to install or operate the tool.

## 2. Problem

Family spending is distributed across multiple people, financial institutions, accounts, cards, and monthly statements. Manually copying transactions into a spreadsheet is slow and error-prone. It also makes consistent categorization, duplicate prevention, historical backfill, and cross-member analysis difficult.

The product must reduce that work without silently trusting imperfect PDF parsing or exposing transaction descriptions to an AI categorization service.

## 3. Goals

The v1 product must:

1. Import text-based PDF statements from AMEX, Bank of America, and Chase.
2. Normalize transactions from different institutions into one consistent ledger.
3. Assign ownership per transaction or cardholder when statement detail permits it.
4. Categorize purchases using editable, local rules learned from prior approvals.
5. Provide an interactive review experience before data is uploaded.
6. Reconcile extracted activity with statement totals.
7. Prevent duplicate transactions and preserve prior reviewed data.
8. Support a resumable, three-year historical backfill.
9. Use Google Sheets as the source of truth for household configuration and approved data.
10. Maintain an automatically updated Google Sheets spending dashboard.
11. Keep original PDFs and raw statement text local.

## 4. Non-goals

The following are explicitly out of scope for v1:

- Live bank connections or credential-based account aggregation
- Scanned-document OCR
- Password-protected PDF processing
- Institutions other than AMEX, Bank of America, and Chase
- Languages other than English
- Currencies other than USD
- Budgets, alerts, or forecasting
- Receipt matching
- Splitting one transaction across multiple categories
- Shared web or mobile applications
- Multi-user CLI credential synchronization
- Currency conversion
- Tax reporting
- AI- or LLM-based transaction categorization
- Local PNG, PDF, or HTML report generation

## 5. Primary user

The primary user is one trusted household administrator who:

- Runs the CLI on macOS.
- Has access to the household statement PDFs.
- Reviews parsing and categorization results.
- Authorizes writes to the household Google workbook.
- Maintains members, aliases, categories, and merchant rules in Google Sheets.

## 6. Core concepts

### 6.1 Statement

A PDF issued by a supported institution for a specific statement period and account. The original PDF is read in place and is not copied by the product.

### 6.2 Transaction

A normalized financial activity row extracted from a statement. Transactions include purchases, merchant credits, fees, interest, payments, transfers, cash advances, and rewards activity even when some types are excluded from spending analysis.

### 6.3 Family member

A stable household member ID configured in the workbook. A member may have multiple aliases matching how their name appears on different statements or cardholder sections.

### 6.4 Merchant rule

An ordered, editable mapping from a normalized merchant description or keyword pattern to an allowed category. Rules are created or updated from approved review decisions and stored in the workbook.

### 6.5 Clean statement

A statement is clean only when all of the following are true:

- The institution and statement format are supported.
- The account and applicable cardholders map to known workbook records.
- All required transaction fields parse successfully.
- Extracted section totals reconcile with reported statement totals.
- Every spending transaction has an allowed category.
- No transaction has a near-duplicate ambiguity.
- No parser warning requires user judgment.

Clean statements may be bulk-approved during backfill. All other statements require individual review.

## 7. End-to-end workflows

### 7.1 First-time setup

1. The user runs `family-spend setup`.
2. The CLI launches browser-based Google OAuth.
3. The user either:
   - Creates a new Family Spend Tracker workbook, or
   - Connects an existing compatible workbook by URL.
4. The CLI initializes or validates the required worksheets.
5. The user configures family members, aliases, accounts, and categories.
6. The CLI stores only the OAuth credentials and workbook ID locally.

### 7.2 Import one statement

1. The user runs `family-spend import <statement.pdf>`.
2. The CLI validates that the file is a readable, text-based, non-password-protected PDF.
3. The institution-specific parser detects the statement format.
4. The CLI loads the current workbook configuration and merchant rules.
5. The parser extracts statement identity, section totals, cardholders, and transactions.
6. Transactions are normalized, assigned to members, typed, categorized, and checked for duplicates.
7. The CLI reconciles extracted values with statement totals.
8. The interactive review table displays the results and all warnings.
9. The user corrects or approves the statement.
10. The CLI uploads approved data and import metadata using an idempotent write.
11. Dashboard data and charts reflect the new transactions.
12. Temporary parsing data is deleted unless cache retention was explicitly requested.

### 7.3 Import a folder

1. The user runs `family-spend import <folder>`.
2. The CLI recursively discovers PDFs in year/month subfolders.
3. The CLI previews the complete detected file list before processing.
4. Files are sorted chronologically when statement dates can be determined.
5. Each supported statement follows the normal import and approval workflow.

### 7.4 Historical backfill

The expected initial backfill is three years of history for two people, each with two to three accounts and approximately two to three statements per month. The likely volume is 150-220 PDFs.

1. The user runs `family-spend backfill <folder>`.
2. The CLI recursively discovers and sorts candidate statements.
3. Already imported statement hashes are skipped.
4. Processing checkpoints after every statement.
5. An interrupted run can continue with `family-spend backfill <folder> --resume`.
6. Clean statements are grouped into a review summary and may be bulk-approved.
7. Statements with exceptions are reviewed individually.
8. A final summary reports imported, skipped, rejected, and unresolved statements.

## 8. Functional requirements

### FR-1: PDF validation and institution detection

- Accept a single PDF path or a directory path.
- Recursively discover `.pdf` files for directory imports.
- Detect AMEX, Bank of America, or Chase from statement content.
- Reject unsupported institutions with a clear, actionable message.
- Reject scanned/image-only, corrupted, or password-protected PDFs.
- Never invoke OCR in v1.
- Never silently guess an institution when detection is ambiguous.

### FR-2: Institution-specific parsing

Each supported parser must extract, where present:

- Institution
- Statement start and end dates
- Statement closing date
- Masked account or card identifier
- Account/cardholder section
- Transaction date
- Posting date, when distinct and available
- Raw description
- Normalized merchant
- Merchant location, when available
- Amount as an exact USD decimal
- Debit/credit direction
- Transaction type
- Reported statement section totals

The parser must preserve enough source context to explain a warning during the active review session without uploading raw statement text.

### FR-3: Member ownership

- Assign ownership at the transaction/cardholder level when the statement exposes that detail.
- Match statement names against aliases in the `Members` worksheet.
- Fall back to the configured account owner when no transaction-level cardholder exists.
- Require user resolution when ownership is missing or ambiguous.
- Never create a new member silently.

### FR-4: Transaction types and spending rules

The normalized transaction types are:

- `purchase`
- `merchant_credit`
- `fee`
- `interest`
- `payment`
- `transfer`
- `cash_advance`
- `rewards`
- `other`

Spending analysis must follow these rules:

- Purchases count as spending.
- Fees count as spending and remain separately filterable.
- Merchant credits and refunds reduce spending in their assigned category.
- Card payments, balance transfers, cash movements, and rewards redemptions do not count as spending.
- Interest is tracked but excluded from the main spending charts.
- Cash advances count as spending and are visibly flagged.
- Negative category totals are valid when credits exceed purchases.

### FR-5: Categorization

- Categorization is rules-based and does not call an AI service.
- Normalize noisy statement descriptions into stable merchant names.
- Apply previously approved merchant mappings first.
- Apply broader ordered keyword rules second.
- Assign unmatched spending transactions to `Uncategorized`.
- Require resolution of uncategorized spending before a statement can be clean.
- Allow the user to save a review correction as a future merchant rule.
- Load the latest rules from Google Sheets before every import.
- Make rule precedence visible and deterministic.

The initial editable category taxonomy is:

- Groceries
- Dining
- Housing
- Utilities
- Transportation
- Shopping
- Health
- Childcare
- Education
- Entertainment
- Travel
- Subscriptions
- Personal Care
- Pets
- Gifts & Donations
- Fees
- Cash
- Other
- Uncategorized

`Uncategorized` is a visible workflow state, not a valid final category for a clean statement.

### FR-6: Interactive review

The terminal review experience must:

- Present transactions in an interactive table.
- Highlight uncertain, invalid, uncategorized, and near-duplicate rows.
- Filter to rows that require attention.
- Allow edits to member, merchant, date, amount, transaction type, and category.
- Allow bulk category assignment for matching merchants.
- Offer to save approved merchant/category corrections as rules.
- Display reported and extracted statement totals.
- Explain reconciliation differences and parser warnings.
- Require explicit approval before upload.
- Allow the user to cancel without partially uploading a statement.

### FR-7: Reconciliation

- Use exact decimal arithmetic; never use binary floating-point for money.
- Compare extracted transaction totals with the corresponding reported statement section totals.
- Reconcile purchases, credits/payments, fees, and interest separately when the statement provides separate totals.
- Treat a difference greater than USD 0.01 as a reconciliation exception.
- Block clean status when reconciliation fails.
- Permit an explicit user override only after showing the difference and recording the reason in import metadata.

### FR-8: Duplicate prevention and idempotency

- Compute a cryptographic hash for each source statement.
- Skip a statement whose hash already exists in `Imports`.
- Generate a stable transaction fingerprint using account/card identity, date, amount, normalized description, and an occurrence discriminator.
- Skip exact transaction duplicates already present in `Transactions`.
- Flag likely near-duplicates for confirmation.
- Never silently overwrite a reviewed transaction row.
- Treat existing Google Sheets transaction rows as the source of truth.
- Make retrying an interrupted or failed upload safe.
- Record the source statement identifier and import timestamp on every uploaded transaction.

### FR-9: Google authentication

- Use browser-based Google OAuth during first-time setup.
- Request only the minimum Google Sheets and Drive permissions required to create or connect and update the workbook.
- Store refresh credentials locally, outside the Git repository.
- Never store credentials in source files or Google Sheets.
- Provide a command to disconnect and remove local credentials.

### FR-10: Workbook creation and validation

- Create a compatible workbook automatically when requested.
- Connect to an existing compatible workbook by URL.
- Validate worksheet names, required columns, IDs, and value types before import.
- Fail safely when the workbook schema is incompatible.
- Do not replace or destructively recreate a worksheet without explicit user action.

### FR-11: Workbook schema

The workbook is the source of truth and contains:

#### `Transactions`

At minimum:

- Transaction ID
- Transaction fingerprint
- Statement/import ID
- Institution
- Masked account ID
- Member ID
- Transaction date
- Posting date
- Raw description
- Normalized merchant
- Merchant location
- Amount
- Transaction type
- Category
- Included in spend
- User-reviewed flag
- Imported timestamp

#### `Members`

At minimum:

- Member ID
- Display name
- Statement aliases
- Active flag

#### `Accounts`

At minimum:

- Account ID
- Institution
- Masked identifier
- Default member ID
- Display name
- Active flag

#### `Categories`

At minimum:

- Category ID
- Display name
- Sort order
- Active flag

#### `Merchant Rules`

At minimum:

- Rule ID
- Match type
- Match value
- Normalized merchant
- Category ID
- Priority
- Active flag
- Last updated timestamp

#### `Imports`

At minimum:

- Import ID
- Source filename
- Statement hash
- Institution
- Masked account ID
- Statement period
- Reconciliation status
- Reconciliation difference
- Override reason
- Transaction count
- Import status
- Imported timestamp

#### `Dashboard`

Contains controls, summary metrics, chart-support tables, and charts. It must not be used as an authoritative transaction store.

### FR-12: Dashboard

The Dashboard defaults to:

- The trailing 12 months
- All family members
- All institutions/accounts
- All categories

It provides controls for:

- Start date
- End date
- Family member
- Institution/account
- Category

It includes:

1. Summary cards for total net spend, average monthly spend, largest category, and uncategorized transaction count.
2. A horizontal spending-by-category bar chart, sorted from highest to lowest net spend.
3. A monthly net-spending column chart.
4. A grouped or stacked family-member comparison by month.
5. A category-by-month supporting table.
6. A ranked top-merchants table.

Dashboard calculations must:

- Include approved transactions only.
- Follow the spending rules in FR-4.
- Update after successful imports and direct transaction edits.
- Keep uncategorized spending visible.
- Allow negative category values.
- Avoid double-counting duplicate rows.

### FR-13: Cache retention

- Delete temporary parser data after each run by default, including after failures.
- Support `--retain-cache` for imports and backfills.
- Retain structured transaction data, parser diagnostics, fingerprints, and review decisions only.
- Never retain full extracted statement text in the cache.
- Never copy the original PDF into the cache.
- Store retained cache files outside the Git repository with owner-only file permissions.
- Identify retained cache files clearly enough for manual deletion.

### FR-14: Error handling and recovery

- Provide actionable errors without printing full account numbers or OAuth secrets.
- Do not upload partial statement data when review is cancelled.
- If a Google write fails, report whether no rows or some rows were written and make retry safe.
- Preserve backfill checkpoints after recoverable failures.
- Continue a backfill past independently rejected files when the user chooses to do so.
- Produce an end-of-run summary with file paths, statuses, and next actions.

## 9. Command requirements

The exact flags may evolve during implementation, but v1 must provide these product capabilities:

```text
family-spend setup
family-spend import <pdf-or-folder> [--retain-cache]
family-spend backfill <folder> [--resume] [--retain-cache]
family-spend status
family-spend validate-workbook
family-spend disconnect
```

`status` reports the connected workbook, authenticated Google identity, last successful import, unresolved exceptions, and retained cache location without exposing secrets.

## 10. Privacy and security

- Original PDFs remain at their supplied paths.
- Raw extracted statement text is never uploaded to Google Sheets.
- Only approved normalized transactions and audit metadata are uploaded.
- Only masked account/card identifiers are stored or displayed.
- Transaction descriptions are never sent to an AI service.
- OAuth credentials and retained caches live outside the repository.
- Generated logs redact full account numbers, credentials, and sensitive PDF metadata.
- Repository ignore rules must cover local credentials, caches, temporary PDFs, extracted text, and environment files.

## 11. Performance and reliability targets

- Support an initial backfill of at least 250 statements and 25,000 transactions.
- Preview a 250-file backfill set without requiring the user to wait for full parsing.
- Checkpoint after every processed statement.
- Resume without reprocessing successfully imported statements.
- Use batch Google Sheets writes where safe.
- Keep review interaction responsive for a statement containing up to 1,000 transactions.
- Produce deterministic parsing and categorization results for the same PDF and workbook configuration.

## 12. Success criteria

The release is successful when:

1. The household administrator can set up or connect a workbook using Google OAuth.
2. Representative AMEX, Bank of America, and Chase text PDFs import successfully.
3. Every uploaded transaction is traceable to an import record.
4. Re-importing the same PDF creates no duplicate rows.
5. Interrupted backfill can resume without duplicating completed work.
6. Clean historical statements can be bulk-approved.
7. Exception statements cannot bypass review silently.
8. Learned merchant mappings categorize later matching transactions consistently.
9. Dashboard totals match approved transaction rows under the documented spend rules.
10. No original PDF, raw extracted statement text, OAuth secret, or full account number enters the Git repository.

## 13. Acceptance scenarios

### Scenario A: Clean AMEX import

Given a supported text-based AMEX statement with known members and merchants, when the user imports it, then the CLI parses and reconciles it, shows a clean review summary, uploads it after approval, and updates the dashboard.

### Scenario B: Unknown merchant

Given a purchase from an unknown merchant, when the statement is reviewed, then the row is marked `Uncategorized`, the user can assign a category and save a merchant rule, and a later matching transaction receives that category automatically.

### Scenario C: Multiple cardholders

Given a statement that groups transactions by cardholder, when it is parsed, then transactions are assigned to the matching member aliases rather than only to the account's default owner.

### Scenario D: Duplicate statement

Given a previously imported PDF, when it is imported again, then the CLI identifies its statement hash, uploads no rows, and explains where and when it was previously imported.

### Scenario E: Near-duplicate transaction

Given a transaction similar but not identical to an existing row, when it is reviewed, then the CLI flags the possible duplicate and requires a keep/skip decision.

### Scenario F: Reconciliation failure

Given a parser result that does not match a reported section total, when review begins, then the discrepancy is displayed, clean approval is blocked, and any override requires an audit reason.

### Scenario G: Resumable backfill

Given a three-year folder backfill interrupted after several statements, when the user reruns it with `--resume`, then completed statements are skipped and processing continues from the checkpoint.

### Scenario H: Cache choice

Given a completed import without `--retain-cache`, then temporary structured parsing data is deleted. Given the same import with `--retain-cache`, then only the structured audit cache is retained outside the repository with restricted permissions.

### Scenario I: Unsupported PDF

Given a scanned, encrypted, corrupted, or unsupported-institution PDF, when it is discovered, then the CLI rejects it with a clear reason and does not upload partial data.

## 14. Release gate

v1 is ready for household use only after:

- Automated parser fixtures cover representative AMEX, Bank of America, and Chase layouts without containing real household data.
- Money, duplicate, reconciliation, and categorization logic have automated tests.
- Google Sheets writes have retry and idempotency tests.
- A full dry-run backfill can complete without uploading.
- A real sample from each institution passes user review.
- Security checks confirm credentials, caches, source PDFs, and extracted text are excluded from Git.
