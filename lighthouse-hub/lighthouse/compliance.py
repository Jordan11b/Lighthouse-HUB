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


def compliance_status(completed, target, has_scheduled_session=True):
    """For a fully-elapsed (past) month. Only a real numeric shortfall counts as "behind" -
    a month where the student was never scheduled at all is a scheduling gap, not an
    attendance failure, so that still takes priority just like in pace_status."""
    if not has_scheduled_session:
        return "needs_scheduling"
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


TWO_WEEK_CHECKPOINT_DAYS = 14


def pace_status(completed, target, active_days, elapsed_days, has_scheduled_session=True):
    """Checkpoint-based status, not a continuous daily proration - a student isn't "behind"
    just because a few days have passed without a session logged yet.

    - A student with nothing scheduled at all this month can't be judged on attendance -
      that's a scheduling gap, not a compliance one ("needs_scheduling" takes priority over
      everything else, and callers should pass has_scheduled_session=False to signal it).
    - Before the two-week mark of their active period, it's too early to say anything -
      always "on_target".
    - From two weeks in through the end of the month, falling short of the halfway point
      is flagged "at_risk" (a heads-up, not a failure) - there's still time left to catch up.
    - Only once the month (or their active period within it) has actually finished does
      falling short of the full target count as "behind" - there's no time left to act.
    """
    if not has_scheduled_session:
        return "needs_scheduling"
    if target <= 0 or active_days <= 0:
        return "on_target"
    if elapsed_days >= active_days:
        return "on_target" if completed >= target else "behind"
    if elapsed_days >= TWO_WEEK_CHECKPOINT_DAYS:
        return "on_target" if completed >= (target * 0.5) else "at_risk"
    return "on_target"
