"""Creates a sign-in account from the command line.

This is how the first account comes into existence: account creation requires
a Super Admin, and before this script runs there are none. It is also the
recovery path if the last admin is ever locked out.

    python scripts/create_user.py --email you@example.com --role super_admin

The password is read with getpass - never passed as an argument, so it does
not land in shell history, `ps` output, or a terminal transcript.
"""

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.graph_db import ensure_bootstrap_tenant, ensure_constraints  # noqa: E402
from db.repositories import user_repository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a PharmaGPT sign-in account.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument(
        "--role", default="super_admin", choices=list(user_repository.ROLES),
        help="Defaults to super_admin, since the usual reason to run this is the first account.",
    )
    parser.add_argument(
        "--password-from-env", metavar="VAR",
        help="Read the password from this environment variable instead of prompting. "
             "For automated tests only - an interactive operator should use the prompt.",
    )
    args = parser.parse_args()

    if args.password_from_env:
        password = os.environ.get(args.password_from_env, "")
        if not password:
            print(f"Environment variable {args.password_from_env} is empty.", file=sys.stderr)
            return 2
    else:
        password = getpass.getpass("Password (min 12 characters): ")
        if password != getpass.getpass("Confirm password: "):
            print("Passwords did not match.", file=sys.stderr)
            return 2

    # The account hangs off the bootstrap Pharmacy, which may not exist yet on
    # a fresh database.
    ensure_constraints()
    ensure_bootstrap_tenant()

    try:
        user = user_repository.create_user(
            email=args.email, name=args.name, password=password, role=args.role,
        )
    except user_repository.UserExistsError as e:
        print(str(e), file=sys.stderr)
        return 1
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    print(f"Created {user['email']} ({user['role']}) with id {user['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
