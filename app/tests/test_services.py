from datetime import date

from expense_app.services import add_months, format_money, month_start, parse_amount


def test_parse_amount():
    assert parse_amount("1,250.50") == 125050
    assert parse_amount("0.005") == 1
    assert parse_amount("12") == 1200
    for bad in ["", "abc", "-1", "0", "NaN", "Infinity", "100000000"]:
        assert parse_amount(bad) is None, bad


def test_format_money():
    assert format_money(125050) == "1,250.50"
    assert format_money(125050, decimals=False) == "1,251"
    assert format_money(None) == "0.00"


def test_months():
    assert add_months(date(2026, 12, 1), 1) == date(2027, 1, 1)
    assert add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert month_start("2026-02") == date(2026, 2, 1)
    assert month_start("garbage") == date.today().replace(day=1)
