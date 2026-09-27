from datetime import date
import pytest
from monitor_billing import next_renewal_date

@pytest.mark.parametrize('anchor,today,period,expected',[
    ('2026-01-31','2026-02-01','月','2026-02-28'),
    ('2026-01-31','2026-03-01','月','2026-03-31'),
    ('2026-01-30','2026-03-01','月','2026-03-30'),
    ('2028-01-31','2028-02-01','月','2028-02-29'),
    ('2026-01-15','2026-12-16','月','2027-01-15'),
    ('2026-01-15','2026-09-15','月','2026-09-15'),
    ('2026-01-15','2026-09-16','月','2026-10-15'),
    ('2027-03-31','2026-09-27','月','2027-03-31'),
    ('2024-02-29','2025-02-01','年','2025-02-28'),
    ('2024-02-29','2028-02-01','年','2028-02-29'),
    ('2024-02-29','2028-03-01','年','2029-02-28'),
])
def test_calendar_rollover_keeps_anchor(anchor,today,period,expected):
    price={'renewal_date':anchor,'period':period}
    assert next_renewal_date(price,date.fromisoformat(today))==expected
    assert price['renewal_date']==anchor

def test_unknown_and_manual_dates_are_not_inferred():
    assert next_renewal_date({}) is None
    assert next_renewal_date({'renewal_date':'2026-01-31','auto_renewal':False},date(2026,9,27))=='2026-01-31'
