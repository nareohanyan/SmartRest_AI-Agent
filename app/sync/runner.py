from __future__ import annotations

import argparse
import json

from app.sync.identity_sync import run_toon_lahmajo_identity_sync


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Toon Lahmajo -> SmartRest canonical identity sync."
    )
    parser.add_argument(
        "--server-name",
        type=str,
        default=None,
        help="Source server_name in source_systems.",
    )
    parser.add_argument(
        "--cloud-num",
        type=int,
        default=None,
        help="Source cloud_num in source_systems.",
    )
    parser.add_argument(
        "--batch-size-profiles",
        type=int,
        default=None,
        help="Profiles stream batch size.",
    )
    parser.add_argument(
        "--batch-size-users",
        type=int,
        default=None,
        help="Users stream batch size.",
    )
    args = parser.parse_args()

    summary = run_toon_lahmajo_identity_sync(
        server_name=args.server_name,
        cloud_num=args.cloud_num,
        batch_size_profiles=args.batch_size_profiles,
        batch_size_users=args.batch_size_users,
    )
    print(
        json.dumps(
            {
                "run_id": summary.run_id,
                "status": summary.status,
                "profiles_processed": summary.profiles_processed,
                "users_processed": summary.users_processed,
                "errors_count": summary.errors_count,
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
