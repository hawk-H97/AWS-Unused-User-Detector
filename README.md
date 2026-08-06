# AWS IAM Identity Center — Multi-Account Inactive User Report

Generates a single **styled Excel (.xlsx)** report of all **IAM Identity
Center (AWS SSO)** users, one row per user, with **one column per AWS
account** (permission sets + last-active date in that account), plus an
overall **30/60/90-day Active/Inactive/Unknown** status computed across
**all your accounts** — a user counts as Active if they signed in to
*any* of the accounts checked within that window.

### Why credentials are asked per account
Identity Center gives you ONE user directory shared across all accounts
(good — no duplicate discovery needed). But **CloudTrail sign-in history
is local to each account** — the management account's CloudTrail does
not see sign-ins that happened in a different member account unless you
have an Organization trail centralizing all logs into one place. So
after discovering your users/accounts from the management account, the
script asks you for Access Key / Secret Key / Session Token **separately
for each distinct account** it found, so it can check that account's own
CloudTrail directly. You can press Enter on Access Key ID to skip an
account you don't have credentials for right now — it will be marked
**"Not checked"**, never confused with "checked and inactive".

Output layout:

| Username | DisplayName | *AccountA (id)* | *AccountB (id)* | Overall Last Active | Overall Days Inactive | Active within 30d? | Active within 60d? | Active within 90d? |
|---|---|---|---|---|---|---|---|---|
| jdoe | John Doe | AdministratorAccess<br>Last active: 2026-08-01 (5d ago) | ReadOnlyAccess<br>[Not checked] | 2026-08-01 | 5 | Active | Active | Active |
| asmith | Ann Smith | PowerUserAccess<br>[No activity in last 90 days] | | | No activity found | Inactive | Inactive | Inactive |

Each account cell shows that user's permission set(s) **and** their last
sign-in date in that specific account (or `[Not checked]` if you skipped
that account's credentials, or `[No activity in last N days]` if it was
checked but nothing was found). The three right-most columns are
color-coded green/red/amber (Active/Inactive/Unknown) so status is
visible at a glance.

- **Account columns are dynamic** — if 4 distinct accounts exist across all
  users, you get 4 account columns automatically. No manual column setup.
- A user's cell under an account column holds **only their permission
  set(s) for that specific account**. If they don't have access to that
  account, the cell is blank.
- Multiple permission sets on the same account go on **separate lines
  within the same cell** (the same visual effect as pressing Alt+Enter in
  Excel), not comma-separated.
- One user = one row, always. No duplicate rows per account/permission set.
- The sheet ships styled: colored header row, alternating row banding,
  borders, frozen header row, and column auto-filters — open it and it's
  ready to read/filter, no manual formatting needed.

---

## Why this repo is split into multiple small files

Instead of one 2,000–4,000 line script, the logic is split so a bug in one
area only ever requires editing one small file:

```
aws-idc-inactive-users/
├── main.py                          # orchestrator only, ~120 lines
├── requirements.txt                 # dependency list (installed automatically)
├── setup.sh / setup.bat             # automated environment setup (Linux/macOS / Windows)
├── run.sh  / run.bat                # convenience: setup (if needed) + run
├── config/
│   └── settings.py                  # all tunable constants live here
├── src/
│   ├── aws_session.py               # collects Access Key / Secret Key / Session Token / Region
│   ├── identity_center_client.py    # identitystore + sso-admin API calls
│   ├── activity_checker.py          # CloudTrail-based "days inactive" logic
│   ├── data_merger.py               # groups assignments per user + finds all distinct accounts
│   └── excel_writer.py              # writes the styled .xlsx (dynamic account columns, colors)
└── output/                          # generated .xlsx reports land here
```

If, say, the CloudTrail logic needs a fix, you only ever open
`src/activity_checker.py` — nothing else changes.

---

## Prerequisites

1. **Python 3.9+** installed and on PATH (Windows or Linux/macOS).
2. IAM Identity Center enabled in your AWS Organization, with the
   **management account** credentials available (Access Key, Secret Key,
   and optionally a Session Token if using temporary credentials).
3. The credentials used must have permission to call:

   | API | Permission |
   |---|---|
   | Identity Store | `identitystore:ListUsers` |
   | SSO Admin | `sso:ListInstances`, `sso:ListPermissionSets`, `sso:DescribePermissionSet`, `sso:ListAccountsForProvisionedPermissionSet`, `sso:ListAccountAssignments` |
   | Organizations *(optional — for account names instead of raw IDs)* | `organizations:DescribeAccount` |
   | CloudTrail *(for the inactivity check)* | `cloudtrail:LookupEvents` |
   | STS *(credential validation)* | `sts:GetCallerIdentity` |

---

## Setup (automated — no manual pip install needed)

### Linux / macOS

```bash
git clone <this-repo-url>
cd aws-idc-inactive-users
chmod +x setup.sh run.sh
./setup.sh
```

`setup.sh` will:
- Detect `python3` (or `python`) on PATH.
- Create a virtual environment in `./venv`.
- Upgrade `pip`.
- Install everything in `requirements.txt` automatically.

### Windows

```bat
git clone <this-repo-url>
cd aws-idc-inactive-users
setup.bat
```

`setup.bat` does the same thing using `venv\Scripts\activate.bat`.

> Both setup scripts are idempotent — running them again just reuses the
> existing `venv` and re-syncs dependencies from `requirements.txt`.

---

## Running the report

### Linux / macOS
```bash
./run.sh
# or manually:
source venv/bin/activate
python main.py
```

### Windows
```bat
run.bat
:: or manually:
venv\Scripts\activate.bat
python main.py
```

You will be prompted (transparently, nothing hardcoded) for:

1. **AWS Access Key ID**
2. **AWS Secret Access Key** (hidden input)
3. **AWS Session Token** (optional — press Enter to skip if using an IAM
   user with long-lived keys instead of temporary/assumed-role credentials)
4. **AWS Region** (e.g. `us-east-1`) — the region your Identity Center
   instance is in
5. **How many days back to check activity** (default/max 90 — see
   Limitations below)

If `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_REGION`
environment variables are already set (e.g. for scheduled/automated runs),
the script uses those instead of prompting — `AWS_SESSION_TOKEN` is
picked up automatically too, if present.

The script prints the authenticated Account ID and ARN before doing
anything else, so you can visually confirm you're pointed at the right
account before it proceeds.

Output is written to `output/idc_inactive_users_<timestamp>.xlsx`.

### Customizing the look

All colors, column widths, and row height live in `config/settings.py`
under the "Excel styling" section (`HEADER_FILL_COLOR`, `BAND_FILL_COLOR`,
`BORDER_COLOR`, etc.) — change the hex codes there, nothing else needs to
change. Colors are standard 6-digit hex (no `#` prefix), e.g. `"1F4E78"`.

---

## Limitations & Extending

- **CloudTrail lookback is capped at 90 days.** `cloudtrail:LookupEvents`
  (Event History) only retains the last 90 days of management events —
  this is an AWS-side limit, not something this script can bypass. If a
  user has no sign-in event in that window, `DaysInactive` will show
  `"No activity in last N days"` instead of a specific number, since we
  can't prove exactly how long they've been inactive, only that it's more
  than N days.
  - For longer/historical windows, point `src/activity_checker.py` at
    **CloudTrail Lake** (via `cloudtrail.start_query`) or **Athena** over
    an Organization trail's S3 logs instead. That's a drop-in replacement
    for the `get_last_activity()` method — nothing else in the repo needs
    to change.
- **Group-based assignments are not expanded.** `main.py` only counts
  assignments where `PrincipalType == USER`. If your org assigns
  permission sets to Identity Center **groups**, add a group→member
  expansion step in `identity_center_client.py` (using
  `identitystore:ListGroupMemberships`) before merging.
- **Account names require `organizations:DescribeAccount`.** Without it,
  the script still works — it just shows the raw account ID instead of
  the friendly name.

---

## Troubleshooting

- **"No IAM Identity Center instance found"** — you're either in the
  wrong region, or Identity Center isn't enabled on this account.
- **`AccessDeniedException` on any `sso-admin`/`identitystore` call** —
  double check the IAM permissions table above.
- **Cells look cramped / lines are cut off** — increase `DATA_ROW_HEIGHT`
  in `config/settings.py`, or just double-click the row border in Excel to
  auto-fit; wrap text is already enabled on every cell.
- **A permission set cell shows one long line instead of separate lines**
  — this means the file was opened by something that stripped the
  embedded line breaks (rare, some older CSV-only viewers). Open it in
  Excel, LibreOffice Calc, or Google Sheets directly — all three render
  `.xlsx` line breaks correctly.
