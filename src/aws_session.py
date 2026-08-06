"""
aws_session.py
---------------
Handles collecting AWS credentials for the MANAGEMENT ACCOUNT (where
IAM Identity Center / SSO is enabled) and building a boto3 Session.

Design goals (per requirements):
  - Transparent: nothing is hardcoded, nothing is silently assumed.
  - User-input driven: prompts for Access Key, Secret Key, Session Token,
    and Region on every run, UNLESS the equivalent environment variables
    are already set (useful for automation/CI, still fully visible/auditable).
  - Validates the credentials immediately via STS so failures happen early,
    not halfway through the report.

This file only knows about "how do I get a working boto3 Session".
It does not know anything about Identity Center or CloudTrail.
"""

import os
import sys
import getpass

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound


def _prompt(label, secret=False, default=None):
    suffix = f" [{default}]" if default else ""
    if secret:
        value = getpass.getpass(f"{label}{suffix}: ")
    else:
        value = input(f"{label}{suffix}: ").strip()
    if not value and default is not None:
        return default
    return value


def ask_int(label, default, minimum=1):
    """Prompts for an integer, re-asking on invalid input. Enter = default."""
    while True:
        raw = input(f"{label} [default {default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
            if value < minimum:
                print(f"[WARN] Must be at least {minimum}.")
                continue
            return value
        except ValueError:
            print("[WARN] Please enter a whole number.")


def _collect_from_env():
    """Return credential dict if ALL required env vars are present, else None."""
    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    session_token = os.environ.get("AWS_SESSION_TOKEN")  # optional (only for temp creds)

    if access_key and secret_key and region:
        return {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "aws_session_token": session_token or None,
            "region_name": region,
        }
    return None


def _collect_interactively():
    print("\n--- AWS Management Account Credentials ---")
    print("These credentials must belong to (or be able to reach) the AWS")
    print("account where IAM Identity Center / AWS SSO is enabled.")
    print("Leave 'Session Token' blank if you are using a long-lived IAM user.\n")

    access_key = _prompt("AWS Access Key ID")
    secret_key = _prompt("AWS Secret Access Key", secret=True)
    session_token = _prompt("AWS Session Token (leave blank if not using temporary credentials)")
    region = _prompt("AWS Region (e.g. us-east-1)", default="us-east-1")

    return {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "aws_session_token": session_token or None,
        "region_name": region,
    }


def _build_and_validate(creds, expected_account_id=None):
    """
    Builds a boto3.Session from a creds dict and validates it via STS.
    Returns (session, identity_dict) or (None, None) if auth fails.
    If expected_account_id is given and the authenticated account differs,
    prints a warning but still returns the session (the user may be
    intentionally pointing at a different account than IdC reported, e.g.
    a delegated audit account with a CloudTrail org trail).
    """
    try:
        session = boto3.Session(**creds)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
    except (ClientError, NoCredentialsError, ProfileNotFound) as exc:
        print(f"[ERROR] Could not authenticate with the provided credentials: {exc}")
        return None, None

    print("[SUCCESS] Authenticated to AWS.")
    print(f"          Account : {identity.get('Account')}")
    print(f"          ARN     : {identity.get('Arn')}")
    print(f"          Region  : {creds['region_name']}")

    if expected_account_id and identity.get("Account") != expected_account_id:
        print(f"[WARN] These credentials authenticate to account "
              f"{identity.get('Account')}, not the expected {expected_account_id}. "
              f"Continuing anyway - make sure this is intentional "
              f"(e.g. a delegated CloudTrail/audit account).")

    return session, identity


def get_account_session(account_label, account_id, default_region):
    """
    Interactively (transparently - nothing hardcoded, nothing hidden)
    collects Access Key / Secret Key / Session Token for ONE member
    account, PLUS the list of regions to check CloudTrail in for that
    account (some accounts run workloads in 2+ regions - CloudTrail
    Event History (LookupEvents) is a per-region API, so each region
    needs its own lookup call to catch sign-ins that happened there).

    A user may press Enter on Access Key ID to SKIP this account (e.g. if
    they don't have credentials for it right now) - the caller treats a
    None return as "not checked" rather than "no activity found", so the
    two cases are never confused in the final report.

    Returns (session, account_id_confirmed, regions_list) or
    (None, None, None) if skipped or authentication failed.
    """
    print(f"\n--- Credentials for account: {account_label} ---")
    print("Press Enter on Access Key ID to SKIP this account "
          "(it will be marked 'Not checked' in the report, not 'Inactive').")

    access_key = _prompt("AWS Access Key ID")
    if not access_key:
        print(f"[INFO] Skipping account {account_label} - no credentials supplied.")
        return None, None, None

    secret_key = _prompt("AWS Secret Access Key", secret=True)
    session_token = _prompt("AWS Session Token (leave blank if not using temporary credentials)")

    num_regions = ask_int(
        f"How many regions do you want to check CloudTrail activity in for "
        f"'{account_label}'? (e.g. 1 if this account only runs in one region, "
        f"2 or 3 if it has workloads/logins across multiple)",
        default=1,
    )

    regions = []
    for i in range(1, num_regions + 1):
        r = _prompt(
            f"  Region {i} of {num_regions} for '{account_label}'",
            default=default_region or "us-east-1",
        )
        regions.append(r)

    creds = {
        "aws_access_key_id": access_key,
        "aws_secret_access_key": secret_key,
        "aws_session_token": session_token or None,
        "region_name": regions[0],  # only used for the STS validation call below
    }

    print(f"\n[INFO] Validating credentials for {account_label}...")
    session, identity = _build_and_validate(creds, expected_account_id=account_id)
    if session is None:
        return None, None, None
    return session, identity.get("Account"), regions


def get_boto3_session():
    """
    Returns a validated boto3.Session and prints the caller identity so the
    user can visually confirm they are pointed at the right account.

    Order of precedence:
      1. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION env vars
         (AWS_SESSION_TOKEN optional) - useful for scripted/automated runs.
      2. Interactive prompts (default, most transparent path).
    """
    creds = _collect_from_env()
    source = "environment variables"

    if creds is None:
        creds = _collect_interactively()
        source = "interactive input"

    print(f"\n[INFO] Building AWS session from {source}...")

    session, identity = _build_and_validate(creds)
    if session is None:
        sys.exit(1)

    return session, identity.get("Account"), creds["region_name"]
