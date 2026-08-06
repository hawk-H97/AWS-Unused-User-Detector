"""
data_merger.py
---------------
A single Identity Center user can be assigned MANY permission sets across
MANY accounts. This module groups the flat assignment list into ONE
record per user, keeping accounts/permission sets as structured data
(not pre-joined strings) so excel_writer.py can lay each account out as
its own column.

Input : a flat list of assignment dicts, one per (user, account, permission set)
        combination:
        {
            "UserId": "...",
            "UserName": "...",
            "DisplayName": "...",
            "AccountId": "111111111111",
            "AccountName": "MyAccount",
            "PermissionSetName": "AdministratorAccess",
        }

Output: OrderedDict keyed by UserId -> merged record:
        {
            "UserName": "...",
            "DisplayName": "...",
            "accounts": {
                "MyAccount (111111111111)": {"AdministratorAccess", "ReadOnly"},
                "OtherAccount (222222222222)": {"PowerUser"},
            },
            # "DaysInactive" is added later by main.py after the activity check
        }
"""

from collections import OrderedDict
from datetime import datetime, timezone

from config.settings import (
    ACTIVITY_THRESHOLDS_DAYS,
    ACTIVE_LABEL,
    INACTIVE_LABEL,
    UNKNOWN_LABEL,
)


def merge_user_data(assignments):
    """
    assignments: flat list of per-(user, account, permission set) dicts (see module docstring)

    Returns: OrderedDict keyed by UserId -> merged record. Each record's
    "accounts" dict maps account_label -> {
        "permission_sets": set of names,
        "last_active": None,        # filled in later by apply_account_activity()
        "days_inactive": None,      # int, or a descriptive string, or None if not yet checked
        "checked": False,           # True once we actually queried CloudTrail for this account
    }
    """
    grouped = OrderedDict()

    for row in assignments:
        user_id = row["UserId"]
        if user_id not in grouped:
            grouped[user_id] = {
                "UserName": row["UserName"],
                "DisplayName": row["DisplayName"],
                "accounts": OrderedDict(),
            }

        account_label = f"{row['AccountName']} ({row['AccountId']})"
        accounts = grouped[user_id]["accounts"]
        if account_label not in accounts:
            accounts[account_label] = {
                "permission_sets": set(),
                "last_active": None,
                "days_inactive": None,
                "checked": False,
            }
        accounts[account_label]["permission_sets"].add(row["PermissionSetName"])

    return grouped


def get_all_account_labels(grouped):
    """
    Returns a sorted list of every unique 'AccountName (AccountId)' label
    seen across all users. This becomes the set of dynamic account
    columns in the Excel output - e.g. if 4 distinct accounts exist
    across all users, you get 4 account columns, regardless of how many
    accounts any single user has.
    """
    labels = set()
    for record in grouped.values():
        labels.update(record["accounts"].keys())
    return sorted(labels, key=lambda s: s.lower())


def apply_account_activity(grouped, account_label, activity_by_username):
    """
    Writes CloudTrail results for ONE account back into `grouped`, for
    every user who has an assignment on that account.

    activity_by_username: {username: (last_active_datetime_or_None,
                                       days_inactive_int_or_label_string)}
                           as returned by ActivityChecker.get_last_activity().
                           A username missing from this dict means the
                           lookup for that account was skipped entirely
                           (no credentials supplied) - "checked" stays False.
    """
    for record in grouped.values():
        acct = record["accounts"].get(account_label)
        if acct is None:
            continue  # this user has no assignment on this account
        username = record["UserName"]
        if username not in activity_by_username:
            continue  # account was skipped - leave "checked": False
        last_active, days_inactive = activity_by_username[username]
        acct["last_active"] = last_active
        acct["days_inactive"] = days_inactive
        acct["checked"] = True


def compute_overall_activity(grouped, thresholds_days=None):
    """
    For each user, looks across ALL their checked accounts and finds the
    single most recent sign-in (i.e. the account they were most recently
    active in). Adds to each record:
        "OverallLastActive"   -> datetime or None
        "OverallDaysInactive" -> int or None (None only if no account was
                                  ever checked for this user)
        "AnyAccountChecked"   -> bool
        "Active_<N>d"         -> "Active" / "Inactive" / "Unknown" for each
                                  N in thresholds_days
    A user only counts as "Active" for a threshold if a sign-in was found
    (in ANY checked account) within that many days - this matches the
    requirement "if the user is active in one or more accounts, they're
    considered safe".
    """
    if thresholds_days is None:
        thresholds_days = ACTIVITY_THRESHOLDS_DAYS

    for record in grouped.values():
        best_dt = None
        any_checked = False
        for acct in record["accounts"].values():
            if acct["checked"]:
                any_checked = True
            if acct["last_active"] is not None:
                if best_dt is None or acct["last_active"] > best_dt:
                    best_dt = acct["last_active"]

        record["AnyAccountChecked"] = any_checked

        if best_dt is not None:
            now = datetime.now(timezone.utc)
            overall_days = (now - best_dt).days
            record["OverallLastActive"] = best_dt
            record["OverallDaysInactive"] = overall_days
        else:
            record["OverallLastActive"] = None
            record["OverallDaysInactive"] = None

        for n in thresholds_days:
            key = f"Active_{n}d"
            if not any_checked:
                record[key] = UNKNOWN_LABEL
            elif record["OverallDaysInactive"] is not None and record["OverallDaysInactive"] <= n:
                record[key] = ACTIVE_LABEL
            else:
                record[key] = INACTIVE_LABEL
