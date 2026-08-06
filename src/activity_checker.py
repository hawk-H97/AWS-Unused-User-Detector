"""
activity_checker.py
--------------------
Determines "how many days inactive" a user is, based on CloudTrail
sign-in related events (ConsoleLogin / AssumeRoleWithSAML / Federate)
in the account where this script is run (normally the management /
audit account, ideally one that receives an Organization trail).

IMPORTANT LIMITATION (documented, not hidden):
CloudTrail's lookup_events API (Event History) only retains the last
90 days of management events, regardless of the "days" value you pass
in. If you need longer lookback windows, point this at a CloudTrail
Lake / Athena query instead - see README.md "Limitations & Extending".

Required IAM permission:
  cloudtrail:LookupEvents
"""

from datetime import datetime, timedelta, timezone

from config.settings import (
    SIGN_IN_EVENT_NAMES,
    NO_ACTIVITY_LABEL_TEMPLATE,
    MAX_CLOUDTRAIL_LOOKBACK_DAYS,
)


class ActivityChecker:
    def __init__(self, session, region, lookback_days):
        self.cloudtrail = session.client("cloudtrail", region_name=region)
        # CloudTrail Event History hard limit is 90 days.
        self.lookback_days = min(lookback_days, MAX_CLOUDTRAIL_LOOKBACK_DAYS)
        self.now = datetime.now(timezone.utc)
        self.start_time = self.now - timedelta(days=self.lookback_days)

    def get_last_activity(self, username):
        """
        Returns (last_activity_datetime_or_None, days_inactive_or_label).

        last_activity_datetime is None if no matching sign-in event was
        found within the lookback window - in that case days_inactive is
        a descriptive label string instead of an int, since we cannot
        prove HOW inactive the user is, only that it exceeds the window.
        """
        latest_event_time = None

        paginator = self.cloudtrail.get_paginator("lookup_events")
        try:
            for page in paginator.paginate(
                LookupAttributes=[{"AttributeKey": "Username", "AttributeValue": username}],
                StartTime=self.start_time,
                EndTime=self.now,
            ):
                for event in page.get("Events", []):
                    if event.get("EventName") not in SIGN_IN_EVENT_NAMES:
                        continue
                    event_time = event["EventTime"]
                    if latest_event_time is None or event_time > latest_event_time:
                        latest_event_time = event_time
        except Exception as exc:
            # Don't let one user's CloudTrail lookup crash the whole run.
            print(f"[WARN] CloudTrail lookup failed for '{username}': {exc}")
            return None, "Lookup failed"

        if latest_event_time is None:
            label = NO_ACTIVITY_LABEL_TEMPLATE.format(days=self.lookback_days)
            return None, label

        days_inactive = (self.now - latest_event_time).days
        return latest_event_time, days_inactive
