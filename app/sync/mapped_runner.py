from __future__ import annotations

import argparse
import json

from app.sync.mapped_table_sync import run_toon_lahmajo_mapped_table_sync


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Toon Lahmajo -> SmartRest mapped table sync."
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
        "--batch-size",
        type=int,
        default=None,
        help="Mapped table batch size.",
    )
    parser.add_argument(
        "--max-batches-per-table",
        type=int,
        default=None,
        help="Maximum number of batches processed per selected table in this run.",
    )
    parser.add_argument(
        "--include-table",
        action="append",
        default=[],
        help="Optional source/destination table name to include. Repeatable.",
    )
    parser.add_argument(
        "--exclude-table",
        action="append",
        default=[],
        help="Optional source/destination table name to exclude. Repeatable.",
    )
    args = parser.parse_args()

    summary = run_toon_lahmajo_mapped_table_sync(
        server_name=args.server_name,
        cloud_num=args.cloud_num,
        batch_size=args.batch_size,
        max_batches_per_table=args.max_batches_per_table,
        include_tables=tuple(args.include_table),
        exclude_tables=tuple(args.exclude_table),
    )
    print(
        json.dumps(
            {
                "run_id": summary.run_id,
                "status": summary.status,
                "tables_total": summary.tables_total,
                "tables_synced": summary.tables_synced,
                "rows_processed": summary.rows_processed,
                "errors_count": summary.errors_count,
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
