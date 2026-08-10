"""Monthly requirement, proration, and compliance % calculations.

Rules taken from the spec:
- The Hub automatically prorates requirements when service begins or ends
  partway through a month.
- Prorated requirements always round up to a whole session (2.2 -> 3).
- School-controlled interruptions are excluded from Lighthouse's compliance
  calculation (i.e. they don't count against the provider/clinic).
- Standard monthly target is derived from the student's weekly frequency.
"""
import calendar
import datetime
import math

WEEKS_PER_MONTH = 4.345  # average calendar weeks in a month, used for the standard target


def _parse_date(s):
    if not s:
        return None
    return datetime.date.fromisoformat(s[:10])


def days_in_month(year, month):
    return calendar.monthrange(year, month)[1]


def standard_monthly_target(sessions_per_week):
    """Full-month target for a student attending every week of that month."""
    return max(0, round(sessions_per_week * WEEKS_PER_MONTH))


def prorated_target(sessions_per_week, service_start, service_end, year, month, target_override=None):
    """Returns (standard_target, prorated_target, active_days, days_in_month, is_prorated)."""
    dim = days_in_month(year, month)
    month_start = datetime.date(year, month, 1)
    month_end = datetime.date(year, month, dim)

    start = _parse_date(service_start) or month_start
    end = _parse_date(service_end) or month_end

    active_start = max(start, month_start)
    active_end = min(end, month_end)

    if active_start > active_end:
        active_days = 0
    else:
        active_days = (active_end - active_start).days + 1

    standard = standard_monthly_target(sessions_per_week)

    if target_override is not None:
        return standard, target_override, active_days, dim, True

    if active_days >= dim:
        return standard, standard, active_days, dim, False

    if active_days <= 0:
        return standard, 0, active_days, dim, True

    raw = standard * (active_days / dim)
    prorated = math.ceil(raw - 1e-9)  # round UP to a whole session, per spec
    return standard, prorated, active_days, dim, True


SCHOOL_CONTROLLED_RESULTS = {
    "student_absent", "student_refused", "school_closed", "school_testing",
    "field_trip", "assembly", "school_directed_unavailability", "other_excused",
}

MAKEUP_REQUIRED_RESULTS = {"provider_absent", "provider_cancelled"}


def counts_toward_completed(result):
    return result == "completed"


def is_school_controlled(result):
    return result in SCHOOL_CONTROLLED_RESULTS


def requires_makeup(result):
    return result in MAKEUP_REQUIRED_RESULTS


def compliance_status(completed, target):
    if target <= 0:
        return "on_target"
    pct = completed / target
    if pct >= 1.0:
        return "on_target"
    if pct >= 0.7:
        return "at_risk"
    return "behind"


def elapsed_active_days(service_start, service_end, year, month, as_of=None):
    """How many of the student's active days in this month have occurred so far."""
    dim = days_in_month(year, month)
    month_start = datetime.date(year, month, 1)
    month_end = datetime.date(year, month, dim)
    start = _parse_date(service_start) or month_start
    end = _parse_date(service_end) or month_end
    active_start = max(start, month_start)
    active_end = min(end, month_end)
    today = as_of or datetime.date.today()
    cap = min(active_end, today)
    if active_start > cap:
        return 0
    return (cap - active_start).days + 1


def pace_status(completed, target, active_days, elapsed_days):
    """Status based on progress-to-date within the active period, not the full-month
    target - a student isn't "behind" on day 3 of a 20-day month just because they
    haven't hit the whole month's target yet."""
    if target <= 0 or active_days <= 0:
        return "on_target"
    expected_by_now = target * min(1.0, elapsed_days / active_days)
    if expected_by_now <= 0:
        return "on_target"
    pct = completed / expected_by_now
    if pct >= 1.0:
        return "on_target"
    if pct >= 0.7:
        return "at_risk"
    return "behind"
