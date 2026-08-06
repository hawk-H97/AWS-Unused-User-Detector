"""
main.py
-------
Entry point. Orchestrates the small, single-purpose modules in src/ to
produce one CSV listing every IAM Identity Center user, their merged
account + permission set assignments, and how many days inactive they are.

Run:
    python main.py

This file intentionally contains almost no logic of its own - each real
step lives in its own file under src/, so a bug in one area only ever
requires editing one small file.
"""

import os
import sys
from datetime import datetime

from tqdm import tqdm

from src.aws_session import get_boto3_session, get_account_session, ask_int
from src.identity_center_client import IdentityCenterClient
from src.activity_checker import ActivityChecker
from src.data_merger import (
    merge_user_data,
    get_all_account_labels,
    apply_account_activity,
    compute_overall_activity,
)
from src.excel_writer import write_excel
from config.settings import (
    OUTPUT_DIR,
    OUTPUT_FILENAME_PREFIX,
    OUTPUT_EXTENSION,
    DEFAULT_CLOUDTRAIL_LOOKBACK_DAYS,
    ACTIVITY_THRESHOLDS_DAYS,
)


def ask_lookback_days():
    raw = input(
        f"\nHow many days back should sign-in activity be checked? "
        f"[default {DEFAULT_CLOUDTRAIL_LOOKBACK_DAYS}, max {DEFAULT_CLOUDTRAIL_LOOKBACK_DAYS} "
        f"due to CloudTrail Event History limits]: "
    ).strip()
    if not raw:
        return DEFAULT_CLOUDTRAIL_LOOKBACK_DAYS
    try:
        return int(raw)
    except ValueError:
        print("[WARN] Not a number, using default.")
        return DEFAULT_CLOUDTRAIL_LOOKBACK_DAYS


def _extract_account_id(account_label):
    """'MyAccount (111111111111)' -> '111111111111'"""
    if "(" in account_label and account_label.endswith(")"):
        return account_label.rsplit("(", 1)[1][:-1]
    return account_label


def ask_which_accounts_to_check(account_labels):
    """
    Shows the discovered accounts, asks how many the user wants to check
    activity for right now (they may not have credentials for all of
    them in this run), and - if fewer than all - asks which ones by
    number. Returns the subset of account_labels to actually check;
    accounts left out are marked "Not checked" in the final report,
    never confused with "checked, and inactive".
    """
    print(f"\n[INFO] {len(account_labels)} distinct account(s) were discovered "
          f"from Identity Center:")
    for i, label in enumerate(account_labels, start=1):
        print(f"   {i}. {label}")

    num_to_check = ask_int(
        f"\nHow many of these {len(account_labels)} account(s) do you want "
        f"to check activity for right now?",
        default=len(account_labels),
    )
    num_to_check = min(num_to_check, len(account_labels))

    if num_to_check == len(account_labels):
        return account_labels

    print(f"Which {num_to_check} account(s)? Enter their numbers separated by "
          f"commas (e.g. 1,3,4).")
    while True:
        raw = input("Account numbers: ").strip()
        try:
            picked_idx = sorted({int(x.strip()) for x in raw.split(",") if x.strip()})
        except ValueError:
            print("[WARN] Please enter numbers separated by commas.")
            continue
        if len(picked_idx) != num_to_check or any(i < 1 or i > len(account_labels) for i in picked_idx):
            print(f"[WARN] Please enter exactly {num_to_check} valid number(s) "
                  f"between 1 and {len(account_labels)}.")
            continue
        return [account_labels[i - 1] for i in picked_idx]


def main():
    print("=" * 60)
    print(" AWS IAM Identity Center - Inactive User Report")
    print("=" * 60)

    # 1. Credentials for the management account (access key, secret key,
    #    session token, region) - collected transparently via aws_session.py
    session, account_id, region = get_boto3_session()

    lookback_days = ask_lookback_days()

    # 2. Identity Center discovery
    idc = IdentityCenterClient(session, region)
    print("\n[INFO] Locating IAM Identity Center instance...")
    instance_arn, identity_store_id = idc.get_instance()
    print(f"[INFO] Instance ARN      : {instance_arn}")
    print(f"[INFO] Identity Store ID : {identity_store_id}")

    # 3. Pull the full user directory
    print("\n[INFO] Fetching all Identity Center users...")
    users = idc.list_all_users(identity_store_id)
    users_by_id = {u["UserId"]: u for u in users}
    print(f"[INFO] Found {len(users)} users.")

    # 4. Pull permission sets, then which accounts + users each is assigned to
    print("\n[INFO] Fetching permission sets...")
    permission_sets = idc.list_permission_sets(instance_arn)
    print(f"[INFO] Found {len(permission_sets)} permission sets.")

    assignments = []  # flat list, see data_merger.py docstring for shape
    print("\n[INFO] Mapping permission sets -> accounts -> users "
          "(this can take a while on large orgs)...")
    for ps in tqdm(permission_sets, desc="Permission sets", unit="ps"):
        account_ids = idc.list_accounts_for_permission_set(instance_arn, ps["PermissionSetArn"])
        for acct_id in account_ids:
            user_ids = idc.list_user_assignments(instance_arn, acct_id, ps["PermissionSetArn"])
            if not user_ids:
                continue
            account_name = idc.get_account_name(acct_id)
            for user_id in user_ids:
                user = users_by_id.get(user_id)
                if not user:
                    continue  # e.g. group-based principal not in our user list
                assignments.append(
                    {
                        "UserId": user_id,
                        "UserName": user["UserName"],
                        "DisplayName": user["DisplayName"],
                        "AccountId": acct_id,
                        "AccountName": account_name,
                        "PermissionSetName": ps["Name"],
                    }
                )

    if not assignments:
        print("\n[WARN] No user account assignments were found. "
              "Check permissions or whether assignments are group-based "
              "(see README 'Limitations').")
        sys.exit(0)

    # 5. Group accounts/permission sets per user (kept structured, not
    #    joined into strings yet - excel_writer.py needs the raw shape
    #    so it can lay each account out as its own column)
    print("\n[INFO] Grouping accounts + permission sets per user...")
    merged = merge_user_data(assignments)
    print(f"[INFO] {len(merged)} unique users have at least one assignment.")

    account_labels = get_all_account_labels(merged)
    print(f"[INFO] {len(account_labels)} distinct accounts will become their own columns.")

    # 6. Per-account CloudTrail activity check.
    #    IMPORTANT: Identity Center gives us ONE directory of users/assignments
    #    from the management account, but sign-in activity is recorded in
    #    CloudTrail SEPARATELY in each member account (unless you have an
    #    Organization trail funneling every account's events into one place).
    #    So: ask for credentials for EACH distinct account, one at a time,
    #    fully transparently, and query CloudTrail in that account directly.
    print("\n" + "-" * 60)
    print(f" Now collecting credentials to check activity in each account.")
    print(" You will be asked for Access Key / Secret Key / Session Token,")
    print(" and how many region(s) to check, for EACH account separately")
    print(" (press Enter on Access Key ID to skip an account you don't have")
    print(" credentials for right now).")
    print("-" * 60)

    accounts_to_check = ask_which_accounts_to_check(account_labels)

    for account_label in account_labels:
        if account_label not in accounts_to_check:
            print(f"[INFO] '{account_label}' not selected - will be marked "
                  f"'Not checked' in the report.")
            continue

        account_id = _extract_account_id(account_label)
        acct_session, confirmed_account_id, regions = get_account_session(account_label, account_id, region)

        if acct_session is None:
            print(f"[INFO] '{account_label}' will be marked 'Not checked' in the report.")
            continue

        usernames_on_this_account = sorted({
            record["UserName"]
            for record in merged.values()
            if account_label in record["accounts"]
        })

        print(f"[INFO] Checking sign-in activity for {len(usernames_on_this_account)} "
              f"user(s) on '{account_label}' across {len(regions)} region(s) "
              f"({', '.join(regions)}), last {lookback_days} days...")

        # A user's activity for this ACCOUNT is the most recent sign-in
        # found across ANY of that account's regions - one region catching
        # it is enough to prove the user is active there.
        activity_by_username = {}
        for region_name in regions:
            checker = ActivityChecker(acct_session, region_name, lookback_days)
            for username in tqdm(usernames_on_this_account,
                                  desc=f"{account_label[:24]} / {region_name}", unit="user"):
                last_active, days_inactive = checker.get_last_activity(username)
                if username not in activity_by_username:
                    activity_by_username[username] = (last_active, days_inactive)
                else:
                    existing_last, _ = activity_by_username[username]
                    if last_active is not None and (existing_last is None or last_active > existing_last):
                        activity_by_username[username] = (last_active, days_inactive)

        apply_account_activity(merged, account_label, activity_by_username)

    # 7. Roll up per-account activity into overall 30/60/90-day status.
    #    A user is "Active" for a threshold if they signed in to ANY of the
    #    accounts checked within that many days.
    compute_overall_activity(merged, ACTIVITY_THRESHOLDS_DAYS)

    # 8. Write styled Excel report (one column per account, permission
    #    sets + last-active date on separate lines within each cell)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"{OUTPUT_FILENAME_PREFIX}_{timestamp}.{OUTPUT_EXTENSION}"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    write_excel(merged, account_labels, output_path, ACTIVITY_THRESHOLDS_DAYS)

    print("\n" + "=" * 60)
    print(f"[SUCCESS] Report written to: {output_path}")
    print(f"          Users: {len(merged)}   Account columns: {len(account_labels)}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Cancelled by user.")
        sys.exit(1)
