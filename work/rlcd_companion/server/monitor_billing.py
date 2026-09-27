"""Calendar-based renewal estimates; never treat a schedule as payment confirmation."""
from calendar import monthrange
from datetime import date, datetime
from zoneinfo import ZoneInfo

def next_renewal_date(price, today=None):
    anchor=price.get('renewal_date')
    if not anchor: return None
    anchor=date.fromisoformat(anchor)
    today=today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    if not price.get('auto_renewal',True) or anchor>=today:
        return anchor.isoformat()
    def clamped(year,month):
        return date(year,month,min(anchor.day,monthrange(year,month)[1]))
    if price.get('period','月')=='年':
        candidate=clamped(today.year,anchor.month)
        if candidate<today: candidate=clamped(today.year+1,anchor.month)
    else:
        candidate=clamped(today.year,today.month)
        if candidate<today:
            year,month=(today.year+1,1) if today.month==12 else (today.year,today.month+1)
            candidate=clamped(year,month)
    return candidate.isoformat()
