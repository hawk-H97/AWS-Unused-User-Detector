"""
settings.py
-----------
Central place for tunable values. Edit this file if you want to change
defaults WITHOUT touching the logic in src/.
"""

# Default output location (relative to project root)
OUTPUT_DIR = "output"
OUTPUT_FILENAME_PREFIX = "idc_inactive_users"
OUTPUT_EXTENSION = "xlsx"

# How many days back CloudTrail should be searched for sign-in activity
# when the user does not provide a custom value at runtime.
# NOTE: CloudTrail lookup_events (Event History) only retains 90 days by
# default. For longer lookback windows you need CloudTrail Lake / Athena
# over an Organization trail. See README.md "Limitations" section.
DEFAULT_CLOUDTRAIL_LOOKBACK_DAYS = 90
MAX_CLOUDTRAIL_LOOKBACK_DAYS = 90

# CloudTrail event names treated as "sign-in activity" for a user.
SIGN_IN_EVENT_NAMES = [
    "ConsoleLogin",
    "AssumeRoleWithSAML",
    "Federate",
]

# Label used in the report when no activity was found within the lookback
# window (i.e. we cannot prove a last-login date, only that none was seen).
NO_ACTIVITY_LABEL_TEMPLATE = "No activity in last {days} days"

# Shown in an account's cell when that account was SKIPPED (no credentials
# supplied for it), so it is never confused with "checked, and inactive".
NOT_CHECKED_LABEL = "Not checked (no credentials supplied)"

# ---------------------------------------------------------------------
# Multi-account activity thresholds
# ---------------------------------------------------------------------
# A user is reported "Active" for a given threshold if their MOST RECENT
# sign-in event, across ANY of the accounts checked, is within this many
# days. All three are always computed and shown as separate columns -
# nothing to choose at runtime.
ACTIVITY_THRESHOLDS_DAYS = [30, 60, 90]

ACTIVE_LABEL = "Active"
INACTIVE_LABEL = "Inactive"
UNKNOWN_LABEL = "Unknown"  # no account for this user was ever checked

# Date format used for any printed/logged timestamps.
DATE_FORMAT = "%Y-%m-%d"

# ---------------------------------------------------------------------
# Excel layout
# ---------------------------------------------------------------------
# Fixed (non-account) columns, in order.
FIXED_COLUMNS_LEFT = ["Username", "DisplayName"]
# Right-hand summary columns are built dynamically from
# ACTIVITY_THRESHOLDS_DAYS in main.py / excel_writer.py, but the base
# (non-threshold) ones are listed here.
FIXED_COLUMNS_RIGHT_BASE = ["Overall Last Active (any account)", "Overall Days Inactive"]

# Character used to separate multiple permission sets WITHIN one
# account's cell. "\n" renders as a real line break in Excel (the same
# effect as pressing Alt+Enter while typing in a cell), as long as the
# cell has wrap_text=True, which excel_writer.py sets automatically.
PERMISSION_SET_LINE_BREAK = "\n"

# ---------------------------------------------------------------------
# Excel styling ("attractive colors")
# ---------------------------------------------------------------------
HEADER_FILL_COLOR = "1F4E78"       # dark blue
HEADER_FONT_COLOR = "FFFFFF"       # white
HEADER_FONT_SIZE = 11

BAND_FILL_COLOR = "DCE6F1"         # light blue - alternating row banding
BORDER_COLOR = "B7B7B7"            # light grey grid lines

# Column width bounds for the auto-sized account columns.
ACCOUNT_COLUMN_MIN_WIDTH = 20
ACCOUNT_COLUMN_MAX_WIDTH = 40
USERNAME_COLUMN_WIDTH = 22
DISPLAYNAME_COLUMN_WIDTH = 22
DAYS_INACTIVE_COLUMN_WIDTH = 16

# Row height for data rows (accommodates a few wrapped lines of text).
DATA_ROW_HEIGHT = 45
