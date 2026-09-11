"""Dashboard analytics and formula-backed Google Sheets layout."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from family_spend.domain.models import NormalizedTransaction, TransactionType
from family_spend.review import included_in_spend

ALL_FILTER_VALUE = "All"


@dataclass(frozen=True, slots=True)
class DashboardFilters:
    """User-controlled boundaries for one dashboard view."""

    start_date: date
    end_date: date
    member_id: str = ALL_FILTER_VALUE
    institution: str = ALL_FILTER_VALUE
    account_id: str = ALL_FILTER_VALUE
    category_id: str = ALL_FILTER_VALUE

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("dashboard end date must not precede start date")


@dataclass(frozen=True, slots=True)
class DashboardAnalytics:
    """Exact derived values used to verify the workbook dashboard."""

    total_net_spend: Decimal
    average_monthly_spend: Decimal
    largest_category: str | None
    uncategorized_count: int
    cash_advance_count: int
    category_totals: tuple[tuple[str, Decimal], ...]
    monthly_totals: tuple[tuple[date, Decimal], ...]
    member_month_totals: tuple[tuple[date, str, Decimal], ...]
    category_month_totals: tuple[tuple[date, str, Decimal], ...]
    top_merchants: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True, slots=True)
class DashboardChart:
    """One native Google Sheets chart bound to a support range."""

    title: str
    chart_type: str
    source_range: str
    series_count: int
    anchor_row: int
    anchor_column: int
    width: int = 600
    height: int = 320


@dataclass(frozen=True, slots=True)
class DashboardValidation:
    """One dashboard control and its inspectable list source."""

    cell: str
    source_range: str


@dataclass(frozen=True, slots=True)
class DashboardLayout:
    """Values, formulas, controls, and charts for idempotent provisioning."""

    rows: tuple[tuple[object, ...], ...]
    charts: tuple[DashboardChart, ...]
    validations: tuple[DashboardValidation, ...]
    header_ranges: tuple[str, ...] = ()
    member_month_support_range: str = ""
    category_month_support_range: str = ""


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _months_between(start: date, end: date) -> tuple[date, ...]:
    current = _month_start(start)
    final = _month_start(end)
    months: list[date] = []
    while current <= final:
        months.append(current)
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
    return tuple(months)


def _matches(transaction: NormalizedTransaction, filters: DashboardFilters) -> bool:
    return (
        transaction.reviewed
        and included_in_spend(transaction.transaction_type)
        and filters.start_date <= transaction.transaction_date <= filters.end_date
        and (filters.member_id == ALL_FILTER_VALUE or transaction.member_id == filters.member_id)
        and (
            filters.institution == ALL_FILTER_VALUE
            or transaction.institution.value == filters.institution
        )
        and (filters.account_id == ALL_FILTER_VALUE or transaction.account_id == filters.account_id)
        and (
            filters.category_id == ALL_FILTER_VALUE
            or transaction.category_id == filters.category_id
        )
    )


def calculate_dashboard(
    transactions: tuple[NormalizedTransaction, ...],
    filters: DashboardFilters,
) -> DashboardAnalytics:
    """Calculate every dashboard value from approved transaction records."""
    seen: set[str] = set()
    selected_items: list[NormalizedTransaction] = []
    for item in transactions:
        duplicate_key = item.fingerprint or item.transaction_id
        if duplicate_key in seen or not _matches(item, filters):
            continue
        seen.add(duplicate_key)
        selected_items.append(item)
    selected = tuple(selected_items)
    category_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    month_totals: defaultdict[date, Decimal] = defaultdict(Decimal)
    member_month_totals: defaultdict[tuple[date, str], Decimal] = defaultdict(Decimal)
    category_month_totals: defaultdict[tuple[date, str], Decimal] = defaultdict(Decimal)
    merchant_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    uncategorized_count = 0
    cash_advance_count = 0
    for transaction in selected:
        category = transaction.category_id or "uncategorized"
        month = _month_start(transaction.transaction_date)
        member = transaction.member_id or "unassigned"
        amount = transaction.amount.amount
        category_totals[category] += amount
        month_totals[month] += amount
        member_month_totals[(month, member)] += amount
        category_month_totals[(month, category)] += amount
        merchant_totals[transaction.normalized_merchant] += amount
        uncategorized_count += category == "uncategorized"
        cash_advance_count += transaction.transaction_type is TransactionType.CASH_ADVANCE

    months = _months_between(filters.start_date, filters.end_date)
    monthly = tuple((month, month_totals[month]) for month in months)
    total = sum((transaction.amount.amount for transaction in selected), Decimal())
    average = total / len(months)
    categories = tuple(sorted(category_totals.items(), key=lambda item: (-item[1], item[0])))
    largest_category = categories[0][0] if categories else None
    members = tuple(
        (month, member, amount) for (month, member), amount in sorted(member_month_totals.items())
    )
    category_months = tuple(
        (month, category, amount)
        for (month, category), amount in sorted(category_month_totals.items())
    )
    merchants = tuple(sorted(merchant_totals.items(), key=lambda item: (-item[1], item[0]))[:10])
    return DashboardAnalytics(
        total_net_spend=total,
        average_monthly_spend=average,
        largest_category=largest_category,
        uncategorized_count=uncategorized_count,
        cash_advance_count=cash_advance_count,
        category_totals=categories,
        monthly_totals=monthly,
        member_month_totals=members,
        category_month_totals=category_months,
        top_merchants=merchants,
    )


def _eligible_type_pattern() -> str:
    values = (
        transaction_type.value
        for transaction_type in TransactionType
        if included_in_spend(transaction_type)
    )
    return "^(" + "|".join(values) + ")$"


def _column_name(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(ord("A") + remainder) + value
    return value


def build_dashboard_layout(*, member_count: int = 8, category_count: int = 19) -> DashboardLayout:
    """Build the auditable, formula-driven Dashboard sheet definition."""
    member_series_count = max(1, member_count)
    category_series_count = max(1, category_count)
    member_end_column = 23 + member_series_count
    category_start_column = member_end_column + 2
    category_end_column = category_start_column + category_series_count
    filter_columns = tuple(category_end_column + 2 + offset * 2 for offset in range(4))
    cells: dict[tuple[int, int], object] = {}

    def put(row: int, column: int, value: object) -> None:
        cells[(row, column)] = value

    put(2, 1, "Family spending dashboard")
    put(4, 1, "Start date")
    put(4, 2, "=EOMONTH(TODAY(),-12)+1")
    put(5, 1, "End date")
    put(5, 2, "=TODAY()")
    put(6, 1, "Member")
    put(6, 2, ALL_FILTER_VALUE)
    put(7, 1, "Institution")
    put(7, 2, ALL_FILTER_VALUE)
    put(8, 1, "Account")
    put(8, 2, ALL_FILTER_VALUE)
    put(9, 1, "Category")
    put(9, 2, ALL_FILTER_VALUE)

    cards = (
        (4, 4, "Total net spend", "=SUM($N$56:$N)"),
        (
            4,
            6,
            "Average monthly spend",
            '=IFERROR(AVERAGE(FILTER($U$56:$U,$T$56:$T<>"")),0)',
        ),
        (
            4,
            8,
            "Largest category",
            '=IFERROR(INDEX($Q$56:$Q,MATCH(MAX($R$56:$R),$R$56:$R,0)),"None")',
        ),
        (4, 10, "Uncategorized transactions", "=SUM($O$56:$O)"),
        (7, 10, "Cash advances in view", "=SUMPRODUCT($M$56:$M,$L$56:$L)"),
    )
    for row, column, label, formula in cards:
        put(row, column, label)
        put(row + 1, column, formula)

    put(12, 1, "Top merchants")
    put(
        13,
        1,
        "=IFERROR(QUERY(FILTER({$G$56:$G,$N$56:$N},$M$56:$M=1),"
        '"select Col1,sum(Col2) group by Col1 order by sum(Col2) desc limit 10 '
        "label Col1 'Merchant',sum(Col2) 'Net spend'\",0),"
        '{"Merchant","Net spend"})',
    )
    helper_headers = (
        "Date",
        "Month",
        "Member",
        "Institution",
        "Account",
        "Category",
        "Merchant",
        "Transaction type",
        "Approved",
        "Eligible spend type",
        "Eligible net spend",
        "Cash advance",
        "In current view",
        "View net spend",
        "Uncategorized count",
    )
    for column, header in enumerate(helper_headers, start=1):
        put(55, column, header)
    formulas = (
        '=ARRAYFORMULA(IF(Transactions!A3:A="","",IF(ISNUMBER(Transactions!G3:G),'
        "Transactions!G3:G,DATEVALUE(Transactions!G3:G))))",
        '=ARRAYFORMULA(IF(A56:A="","",EOMONTH(A56:A,-1)+1))',
        '=ARRAYFORMULA(IF(A56:A="","",IF(Transactions!F3:F="","unassigned",Transactions!F3:F)))',
        '=ARRAYFORMULA(IF(A56:A="","",Transactions!D3:D))',
        '=ARRAYFORMULA(IF(A56:A="","",Transactions!E3:E))',
        '=ARRAYFORMULA(IF(A56:A="","",IF(Transactions!N3:N="","uncategorized",Transactions!N3:N)))',
        '=ARRAYFORMULA(IF(A56:A="","",Transactions!J3:J))',
        '=ARRAYFORMULA(IF(A56:A="","",Transactions!M3:M))',
        '=ARRAYFORMULA(IF(A56:A="","",(Transactions!P3:P=TRUE)'
        "*(ROW(Transactions!B3:B)=MATCH(Transactions!B3:B,Transactions!B:B,0))))",
        f'=ARRAYFORMULA(IF(A56:A="","",REGEXMATCH(H56:H,"{_eligible_type_pattern()}")))',
        '=ARRAYFORMULA(IF(A56:A="","",IF((I56:I=TRUE)*(J56:J=TRUE),'
        "IF(ISNUMBER(Transactions!L3:L),Transactions!L3:L,VALUE(Transactions!L3:L)),0)))",
        '=ARRAYFORMULA(IF(A56:A="","",(I56:I=TRUE)*(H56:H="cash_advance")))',
        '=ARRAYFORMULA(IF(A56:A="","",(I56:I=TRUE)*(J56:J=TRUE)'
        "*(A56:A>=$B$4)*(A56:A<=$B$5)"
        '*IF($B$6="All",TRUE,C56:C=$B$6)'
        '*IF($B$7="All",TRUE,D56:D=$B$7)'
        '*IF($B$8="All",TRUE,E56:E=$B$8)'
        '*IF($B$9="All",TRUE,F56:F=$B$9)))',
        '=ARRAYFORMULA(IF(A56:A="","",M56:M*K56:K))',
        '=ARRAYFORMULA(IF(A56:A="","",M56:M*(F56:F="uncategorized")))',
    )
    for column, formula in enumerate(formulas, start=1):
        put(56, column, formula)

    put(55, 17, "Category")
    put(55, 18, "Net spend")
    put(
        56,
        17,
        "=IFERROR(QUERY(FILTER({$F$56:$F,$N$56:$N},$M$56:$M=1),"
        '"select Col1,sum(Col2) group by Col1 order by sum(Col2) desc '
        'label Col1 \'\',sum(Col2) \'\'",0),{"No data",""})',
    )
    put(55, 20, "Month")
    put(55, 21, "Net spend")
    put(
        56,
        20,
        "=ARRAYFORMULA(EDATE(EOMONTH($B$4,-1)+1,"
        'SEQUENCE(DATEDIF(EOMONTH($B$4,-1)+1,EOMONTH($B$5,-1)+1,"M")+1,1,0,1)))',
    )
    put(56, 21, '=ARRAYFORMULA(IF(T56:T="","",SUMIF($B$56:$B,T56:T,$N$56:$N)))')
    put(55, 23, "Member spending by month")
    put(
        56,
        23,
        "=IFERROR(QUERY(FILTER({$B$56:$B,$C$56:$C,$N$56:$N},$M$56:$M=1),"
        "\"select Col1,sum(Col3) group by Col1 pivot Col2 label Col1 'Month'\",0),"
        '{"Month","No data"})',
    )
    put(55, category_start_column, "Category by month")
    put(
        56,
        category_start_column,
        "=IFERROR(QUERY(FILTER({$B$56:$B,$F$56:$F,$N$56:$N},$M$56:$M=1),"
        "\"select Col1,sum(Col3) group by Col1 pivot Col2 label Col1 'Month'\",0),"
        '{"Month","No data"})',
    )

    filter_lists = (
        (
            filter_columns[0],
            "Member filter",
            '=IFERROR(FILTER(Members!A3:A,Members!D3:D=TRUE),"")',
        ),
        (
            filter_columns[1],
            "Institution filter",
            '={"amex";"bank_of_america";"chase"}',
        ),
        (
            filter_columns[2],
            "Account filter",
            '=IFERROR(FILTER(Accounts!A3:A,Accounts!F3:F=TRUE),"")',
        ),
        (
            filter_columns[3],
            "Category filter",
            '=IFERROR(FILTER(Categories!A3:A,Categories!D3:D=TRUE),"")',
        ),
    )
    for column, label, formula in filter_lists:
        put(55, column, label)
        put(56, column, ALL_FILTER_VALUE)
        put(57, column, formula)

    max_row = max(row for row, _ in cells)
    max_column = max(column for _, column in cells)
    rows: list[tuple[object, ...]] = []
    for row in range(1, max_row + 1):
        values = [cells.get((row, column), "") for column in range(1, max_column + 1)]
        while values and values[-1] == "":
            values.pop()
        rows.append(tuple(values))

    return DashboardLayout(
        rows=tuple(rows),
        charts=(
            DashboardChart(
                "Net spending by category",
                "BAR",
                f"Q55:R{55 + category_series_count}",
                1,
                2,
                12,
            ),
            DashboardChart("Monthly net spending", "COLUMN", "T55:U200", 1, 18, 12),
            DashboardChart(
                "Member spending by month",
                "COLUMN",
                f"W55:{_column_name(member_end_column)}200",
                member_series_count,
                34,
                12,
            ),
        ),
        validations=(
            *(
                DashboardValidation(
                    f"B{row}",
                    f"{_column_name(column)}56:{_column_name(column)}",
                )
                for row, column in zip(range(6, 10), filter_columns, strict=True)
            ),
        ),
        header_ranges=(
            "A13:B13",
            "A55:O55",
            "Q55:R55",
            "T55:U55",
            f"W55:{_column_name(member_end_column)}55",
            (f"{_column_name(category_start_column)}55:{_column_name(category_end_column)}55"),
        ),
        member_month_support_range=f"W55:{_column_name(member_end_column)}200",
        category_month_support_range=(
            f"{_column_name(category_start_column)}55:{_column_name(category_end_column)}200"
        ),
    )
