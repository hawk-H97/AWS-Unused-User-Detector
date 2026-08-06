"""
identity_center_client.py
--------------------------
Thin wrapper around the two AWS APIs that make up IAM Identity Center:

  - identitystore   -> user directory (list_users)
  - sso-admin        -> permission sets & account assignments

Also uses Organizations (optional, best-effort) to resolve human-readable
account names instead of raw 12-digit account IDs.

Required IAM permissions on the management account principal:
  identitystore:ListUsers
  sso:ListInstances
  sso:ListPermissionSets
  sso:DescribePermissionSet
  sso:ListAccountsForProvisionedPermissionSet
  sso:ListAccountAssignments
  organizations:ListAccounts   (optional - falls back to account ID if missing)
"""

from botocore.exceptions import ClientError


class IdentityCenterClient:
    def __init__(self, session, region):
        self.session = session
        self.sso_admin = session.client("sso-admin", region_name=region)
        self.identitystore = session.client("identitystore", region_name=region)
        try:
            self.organizations = session.client("organizations", region_name=region)
        except Exception:
            self.organizations = None

        self._account_name_cache = {}

    # ------------------------------------------------------------------
    # Instance discovery
    # ------------------------------------------------------------------
    def get_instance(self):
        """Returns (instance_arn, identity_store_id) for the first IDC instance found."""
        resp = self.sso_admin.list_instances()
        instances = resp.get("Instances", [])
        if not instances:
            raise RuntimeError(
                "No IAM Identity Center instance found. Is Identity Center "
                "enabled on this account/region?"
            )
        instance = instances[0]
        return instance["InstanceArn"], instance["IdentityStoreId"]

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    def list_all_users(self, identity_store_id):
        """Returns list of dicts: UserId, UserName, DisplayName."""
        users = []
        paginator = self.identitystore.get_paginator("list_users")
        for page in paginator.paginate(IdentityStoreId=identity_store_id):
            for u in page.get("Users", []):
                display_name = u.get("DisplayName") or u.get("UserName")
                users.append(
                    {
                        "UserId": u["UserId"],
                        "UserName": u.get("UserName", ""),
                        "DisplayName": display_name,
                    }
                )
        return users

    # ------------------------------------------------------------------
    # Permission sets
    # ------------------------------------------------------------------
    def list_permission_sets(self, instance_arn):
        """Returns list of dicts: PermissionSetArn, Name."""
        arns = []
        paginator = self.sso_admin.get_paginator("list_permission_sets")
        for page in paginator.paginate(InstanceArn=instance_arn):
            arns.extend(page.get("PermissionSets", []))

        result = []
        for arn in arns:
            desc = self.sso_admin.describe_permission_set(
                InstanceArn=instance_arn, PermissionSetArn=arn
            )
            name = desc["PermissionSet"]["Name"]
            result.append({"PermissionSetArn": arn, "Name": name})
        return result

    def list_accounts_for_permission_set(self, instance_arn, permission_set_arn):
        """Returns list of account IDs (strings) that have this permission set provisioned."""
        account_ids = []
        paginator = self.sso_admin.get_paginator(
            "list_accounts_for_provisioned_permission_set"
        )
        for page in paginator.paginate(
            InstanceArn=instance_arn, PermissionSetArn=permission_set_arn
        ):
            account_ids.extend(page.get("AccountIds", []))
        return account_ids

    def list_user_assignments(self, instance_arn, account_id, permission_set_arn):
        """
        Returns list of UserId strings that are DIRECTLY assigned this
        permission set on this account (PrincipalType == USER).
        Group-based assignments are not expanded here - see README.
        """
        user_ids = []
        paginator = self.sso_admin.get_paginator("list_account_assignments")
        for page in paginator.paginate(
            InstanceArn=instance_arn,
            AccountId=account_id,
            PermissionSetArn=permission_set_arn,
        ):
            for assignment in page.get("AccountAssignments", []):
                if assignment.get("PrincipalType") == "USER":
                    user_ids.append(assignment["PrincipalId"])
        return user_ids

    # ------------------------------------------------------------------
    # Account name resolution (best-effort, cached)
    # ------------------------------------------------------------------
    def get_account_name(self, account_id):
        if account_id in self._account_name_cache:
            return self._account_name_cache[account_id]

        name = account_id  # fallback
        if self.organizations is not None:
            try:
                resp = self.organizations.describe_account(AccountId=account_id)
                name = resp["Account"]["Name"]
            except ClientError:
                pass  # no organizations:DescribeAccount permission - fall back to ID
            except Exception:
                pass

        self._account_name_cache[account_id] = name
        return name
