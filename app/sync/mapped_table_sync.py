from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import MetaData, inspect, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload, sessionmaker
from sqlalchemy.schema import Table
from sqlalchemy.sql import sqltypes

from app.core.config import get_settings
from app.db.source import get_toon_lahmajo_engine
from app.smartrest.models import (
    MigrationTableMap,
    SourceSystem,
    SyncError,
    SyncRun,
    SyncState,
    get_sync_session_factory,
)


@dataclass(frozen=True)
class ColumnMapping:
    src_column: str
    dst_column: str


@dataclass(frozen=True)
class TableMapping:
    id: int
    src_table: str
    dst_table: str
    src_pk: str
    columns: tuple[ColumnMapping, ...]


@dataclass(frozen=True)
class TableSyncStats:
    src_table: str
    dst_table: str
    processed: int
    errors: int
    last_cursor: int
    batches_processed: int = 0
    stopped_early: bool = False
    skipped: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class MappedSyncRunSummary:
    run_id: int
    status: str
    tables_total: int
    tables_synced: int
    rows_processed: int
    errors_count: int
    table_stats: tuple[TableSyncStats, ...]


class ToonLahmajoMappedTableSync:
    def __init__(
        self,
        *,
        target_session_factory: sessionmaker[Session] | None = None,
        source_engine: Engine | None = None,
    ) -> None:
        self._target_session_factory = target_session_factory or get_sync_session_factory()
        self._source_engine = source_engine or get_toon_lahmajo_engine()

    def run(
        self,
        *,
        server_name: str | None = None,
        cloud_num: int | None = None,
        batch_size: int | None = None,
        max_batches_per_table: int | None = None,
        include_tables: tuple[str, ...] | None = None,
        exclude_tables: tuple[str, ...] | None = None,
    ) -> MappedSyncRunSummary:
        settings = get_settings()
        source_server_name = (
            server_name or settings.sync_source_system_server_name
        ).strip()
        source_cloud_num = (
            cloud_num
            if cloud_num is not None
            else settings.sync_source_system_cloud_num
        )
        table_batch_size = batch_size or settings.sync_batch_size_tables
        if max_batches_per_table is not None and max_batches_per_table < 1:
            raise ValueError("max_batches_per_table must be >= 1")

        with self._target_session_factory() as session:
            source_system_id = _ensure_source_system(
                session=session,
                server_name=source_server_name,
                cloud_num=source_cloud_num,
            )
            sync_run = SyncRun(
                source_system_id=source_system_id,
                status="running",
                profiles_processed=0,
                users_processed=0,
                errors_count=0,
            )
            session.add(sync_run)
            session.commit()
            session.refresh(sync_run)
            sync_run_id = int(sync_run.id)

            try:
                mappings = _load_mappings(session=session)
                mappings = _filter_mappings(
                    mappings=mappings,
                    include_tables=include_tables,
                    exclude_tables=exclude_tables,
                )
                ordered_mappings = _order_mappings_by_fk(
                    mappings=mappings,
                    target_engine=session.get_bind(),
                )

                table_stats: list[TableSyncStats] = []
                with self._source_engine.connect() as source_conn:
                    target_metadata = MetaData()
                    source_columns_cache: dict[str, set[str]] = {}
                    for mapping in ordered_mappings:
                        stat = _sync_table(
                            source_conn=source_conn,
                            session=session,
                            sync_run_id=sync_run_id,
                            source_system_id=source_system_id,
                            mapping=mapping,
                            target_metadata=target_metadata,
                            target_engine=session.get_bind(),
                            source_columns_cache=source_columns_cache,
                            batch_size=table_batch_size,
                            max_batches_per_table=max_batches_per_table,
                        )
                        table_stats.append(stat)
            except Exception as exc:
                session.execute(
                    update(SyncRun)
                    .where(SyncRun.id == sync_run_id)
                    .values(
                        status="failed",
                        finished_at=datetime.now(timezone.utc),
                        details={"fatal_error": str(exc), "mode": "mapped_tables"},
                    )
                )
                session.commit()
                raise

            errors_count = sum(item.errors for item in table_stats)
            rows_processed = sum(item.processed for item in table_stats)
            tables_synced = sum(1 for item in table_stats if not item.skipped)
            status = "success" if errors_count == 0 else "partial"

            session.execute(
                update(SyncRun)
                .where(SyncRun.id == sync_run_id)
                .values(
                    status=status,
                    finished_at=datetime.now(timezone.utc),
                    profiles_processed=rows_processed,
                    users_processed=tables_synced,
                    errors_count=errors_count,
                    details={
                        "mode": "mapped_tables",
                        "rows_processed": rows_processed,
                        "tables_total": len(ordered_mappings),
                        "tables_synced": tables_synced,
                        "table_stats": [
                            {
                                "src_table": item.src_table,
                                "dst_table": item.dst_table,
                                "processed": item.processed,
                                "errors": item.errors,
                                "last_cursor": item.last_cursor,
                                "batches_processed": item.batches_processed,
                                "stopped_early": item.stopped_early,
                                "skipped": item.skipped,
                                "reason": item.reason,
                            }
                            for item in table_stats
                        ],
                    },
                )
            )
            session.commit()

            return MappedSyncRunSummary(
                run_id=sync_run_id,
                status=status,
                tables_total=len(ordered_mappings),
                tables_synced=tables_synced,
                rows_processed=rows_processed,
                errors_count=errors_count,
                table_stats=tuple(table_stats),
            )


def _load_mappings(*, session: Session) -> tuple[TableMapping, ...]:
    rows = session.scalars(
        select(MigrationTableMap)
        .options(selectinload(MigrationTableMap.columns))
        .where(MigrationTableMap.is_active.is_(True))
        .order_by(MigrationTableMap.id)
    ).all()
    mappings: list[TableMapping] = []
    for row in rows:
        src_table = str(row.src_table)
        dst_table = str(row.dst_table)
        src_pk = str(row.src_pk) if row.src_pk is not None else None
        if src_pk is None or not src_pk.strip():
            continue
        mappings.append(
            TableMapping(
                id=int(row.id),
                src_table=src_table,
                dst_table=dst_table,
                src_pk=src_pk,
                columns=tuple(
                    ColumnMapping(
                        src_column=column.src_column,
                        dst_column=column.dst_column,
                    )
                    for column in sorted(row.columns, key=lambda item: int(item.id))
                ),
            )
        )
    return tuple(mappings)


def _filter_mappings(
    *,
    mappings: tuple[TableMapping, ...],
    include_tables: tuple[str, ...] | None,
    exclude_tables: tuple[str, ...] | None,
) -> tuple[TableMapping, ...]:
    include = {name.strip() for name in include_tables or () if name.strip()}
    exclude = {name.strip() for name in exclude_tables or () if name.strip()}
    filtered: list[TableMapping] = []
    for mapping in mappings:
        if include and mapping.src_table not in include and mapping.dst_table not in include:
            continue
        if mapping.src_table in exclude or mapping.dst_table in exclude:
            continue
        filtered.append(mapping)
    return tuple(filtered)


def _order_mappings_by_fk(
    *,
    mappings: tuple[TableMapping, ...],
    target_engine: Engine | Connection,
) -> tuple[TableMapping, ...]:
    if not mappings:
        return mappings

    metadata = MetaData()
    by_dst = {item.dst_table: item for item in mappings}
    for dst_table in by_dst:
        Table(dst_table, metadata, autoload_with=target_engine)

    edges: dict[str, set[str]] = defaultdict(set)
    indegree: dict[str, int] = {dst: 0 for dst in by_dst}
    for dst, table in metadata.tables.items():
        for fk in table.foreign_key_constraints:
            parent = fk.referred_table.name
            if parent in by_dst and parent != dst and dst not in edges[parent]:
                edges[parent].add(dst)
                indegree[dst] += 1

    ready = deque([name for name in by_dst if indegree[name] == 0])
    ordered_names: list[str] = []
    while ready:
        name = ready.popleft()
        ordered_names.append(name)
        for child in edges.get(name, set()):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)

    if len(ordered_names) != len(by_dst):
        for name in by_dst:
            if name not in ordered_names:
                ordered_names.append(name)

    return tuple(by_dst[name] for name in ordered_names)


def _sync_table(
    *,
    source_conn: Connection,
    session: Session,
    sync_run_id: int,
    source_system_id: int,
    mapping: TableMapping,
    target_metadata: MetaData,
    target_engine: Engine | Connection,
    source_columns_cache: dict[str, set[str]],
    batch_size: int,
    max_batches_per_table: int | None,
) -> TableSyncStats:
    target_table = _get_target_table(
        metadata=target_metadata,
        target_engine=target_engine,
        dst_table=mapping.dst_table,
    )
    target_columns = {column.name for column in target_table.columns}

    source_columns = _get_source_columns(
        source_conn=source_conn,
        src_table=mapping.src_table,
        cache=source_columns_cache,
    )
    if mapping.src_pk not in source_columns:
        return TableSyncStats(
            src_table=mapping.src_table,
            dst_table=mapping.dst_table,
            processed=0,
            errors=0,
            last_cursor=_stream_cursor(
                session=session,
                source_system_id=source_system_id,
                stream_name=_stream_name(mapping.src_table),
            ),
            skipped=True,
            reason="source_table_or_pk_missing",
        )

    mapped_columns = tuple(
        item
        for item in mapping.columns
        if item.dst_column in target_columns and item.src_column in source_columns
    )
    if not mapped_columns:
        return TableSyncStats(
            src_table=mapping.src_table,
            dst_table=mapping.dst_table,
            processed=0,
            errors=0,
            last_cursor=_stream_cursor(
                session=session,
                source_system_id=source_system_id,
                stream_name=_stream_name(mapping.src_table),
            ),
            skipped=True,
            reason="no_destination_columns_mapped",
        )

    pk_columns = [column.name for column in target_table.primary_key.columns]
    if not pk_columns:
        return TableSyncStats(
            src_table=mapping.src_table,
            dst_table=mapping.dst_table,
            processed=0,
            errors=0,
            last_cursor=_stream_cursor(
                session=session,
                source_system_id=source_system_id,
                stream_name=_stream_name(mapping.src_table),
            ),
            skipped=True,
            reason="destination_table_has_no_primary_key",
        )
    mapped_dst_columns = {item.dst_column for item in mapped_columns}
    if not all(column in mapped_dst_columns for column in pk_columns):
        return TableSyncStats(
            src_table=mapping.src_table,
            dst_table=mapping.dst_table,
            processed=0,
            errors=0,
            last_cursor=_stream_cursor(
                session=session,
                source_system_id=source_system_id,
                stream_name=_stream_name(mapping.src_table),
            ),
            skipped=True,
            reason="pk_not_fully_mapped",
        )

    processed = 0
    errors = 0
    batches_processed = 0
    stopped_early = False
    cursor = _stream_cursor(
        session=session,
        source_system_id=source_system_id,
        stream_name=_stream_name(mapping.src_table),
    )
    query_columns = _dedupe_preserve_order(
        [mapping.src_pk, *[item.src_column for item in mapped_columns]]
    )

    while True:
        rows = source_conn.execute(
            text(
                f"""
                SELECT {", ".join(_quote_mysql_ident(column) for column in query_columns)}
                FROM {_quote_mysql_ident(mapping.src_table)}
                WHERE {_quote_mysql_ident(mapping.src_pk)} > :cursor
                ORDER BY {_quote_mysql_ident(mapping.src_pk)}
                LIMIT :batch_size
                """
            ),
            {"cursor": cursor, "batch_size": batch_size},
        ).mappings().all()
        if not rows:
            break

        payloads: list[dict[str, Any]] = []
        row_context: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            row_pk = _safe_int(row.get(mapping.src_pk))
            if row_pk is None:
                errors += 1
                _record_sync_error(
                    session=session,
                    sync_run_id=sync_run_id,
                    source_system_id=source_system_id,
                    stream_name=_stream_name(mapping.src_table),
                    entity_key=None,
                    error_code="invalid_source_pk",
                    error_message=f"Unable to parse source pk {mapping.src_pk!r}",
                    payload_fragment=dict(row),
                )
                continue

            payload = _normalize_payload_for_target(
                raw_payload={
                    column.dst_column: row.get(column.src_column)
                    for column in mapped_columns
                },
                target_table=target_table,
            )
            payloads.append(payload)
            row_context.append((row_pk, payload))

        if payloads:
            stop_due_to_row_failure = False
            try:
                with session.begin_nested():
                    _upsert_payload_batch(
                        session=session,
                        target_table=target_table,
                        payloads=payloads,
                        pk_columns=pk_columns,
                    )
                processed += len(payloads)
                cursor = max(pk for pk, _ in row_context)
            except SQLAlchemyError:
                for row_pk, payload in row_context:
                    try:
                        with session.begin_nested():
                            _upsert_payload_batch(
                                session=session,
                                target_table=target_table,
                                payloads=[payload],
                                pk_columns=pk_columns,
                            )
                        processed += 1
                        cursor = max(cursor, row_pk)
                    except Exception as exc:  # pragma: no cover - guarded path
                        skippable_error_code = _classify_skippable_row_error(exc)
                        errors += 1
                        _record_sync_error(
                            session=session,
                            sync_run_id=sync_run_id,
                            source_system_id=source_system_id,
                            stream_name=_stream_name(mapping.src_table),
                            entity_key=str(row_pk),
                            error_code=skippable_error_code or "mapped_table_upsert_failed",
                            error_message=str(exc),
                            payload_fragment={"src_table": mapping.src_table, "pk": row_pk},
                        )
                        if skippable_error_code is not None:
                            cursor = max(cursor, row_pk)
                            continue
                        stop_due_to_row_failure = True
                        break

        _upsert_stream_state(
            session=session,
            source_system_id=source_system_id,
            stream_name=_stream_name(mapping.src_table),
            last_cursor=cursor,
        )
        session.commit()
        batches_processed += 1
        if (
            max_batches_per_table is not None
            and batches_processed >= max_batches_per_table
        ):
            stopped_early = True
            break
        if payloads and stop_due_to_row_failure:
            break

    return TableSyncStats(
        src_table=mapping.src_table,
        dst_table=mapping.dst_table,
        processed=processed,
        errors=errors,
        last_cursor=cursor,
        batches_processed=batches_processed,
        stopped_early=stopped_early,
    )


def _upsert_payload_batch(
    *,
    session: Session,
    target_table: Table,
    payloads: list[dict[str, Any]],
    pk_columns: list[str],
) -> None:
    stmt = pg_insert(target_table).values(payloads)
    mutable_columns = [column for column in payloads[0].keys() if column not in pk_columns]
    if mutable_columns:
        stmt = stmt.on_conflict_do_update(
            index_elements=[target_table.c[column] for column in pk_columns],
            set_={column: stmt.excluded[column] for column in mutable_columns},
        )
    else:
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[target_table.c[column] for column in pk_columns],
        )
    session.execute(stmt)


def _get_target_table(
    *,
    metadata: MetaData,
    target_engine: Engine | Connection,
    dst_table: str,
) -> Table:
    if dst_table in metadata.tables:
        return metadata.tables[dst_table]
    return Table(dst_table, metadata, autoload_with=target_engine)


def _normalize_payload_for_target(
    *,
    raw_payload: dict[str, Any],
    target_table: Table,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for dst_column, value in raw_payload.items():
        target_column = target_table.c.get(dst_column)
        if target_column is None:
            normalized[dst_column] = value
            continue
        if _is_nullable_foreign_key(target_column):
            fk_normalized = _normalize_nullable_fk_sentinel(value)
            if fk_normalized is None:
                normalized[dst_column] = None
                continue
        normalized[dst_column] = _normalize_value_for_type(
            value=value,
            target_type=target_column.type,
        )
    return normalized


def _normalize_value_for_type(*, value: Any, target_type: sqltypes.TypeEngine[Any]) -> Any:
    if isinstance(target_type, sqltypes.DateTime):
        return _normalize_datetime_value(value)
    if isinstance(target_type, sqltypes.Date):
        return _normalize_date_value(value)
    if isinstance(target_type, sqltypes.Boolean):
        return _normalize_boolean_value(value)
    if isinstance(target_type, sqltypes.JSON):
        return _normalize_json_value(value)
    return value


def _normalize_datetime_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
        if epoch == 0:
            return None
        if abs(epoch) > 10**12:
            epoch /= 1000.0
        return datetime.fromtimestamp(epoch, tz=timezone.utc)
    if isinstance(value, str):
        text_value = value.strip()
        if text_value == "":
            return None
        numeric_value = _parse_numeric(text_value)
        if numeric_value is not None:
            epoch = numeric_value
            if epoch == 0:
                return None
            if abs(epoch) > 10**12:
                epoch /= 1000.0
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        parsed = _parse_datetime_string(text_value)
        if parsed is not None:
            return parsed
    return value


def _normalize_date_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        epoch = float(value)
        if epoch == 0:
            return None
        if abs(epoch) > 10**12:
            epoch /= 1000.0
        return datetime.fromtimestamp(epoch, tz=timezone.utc).date()
    if isinstance(value, str):
        text_value = value.strip()
        if text_value == "":
            return None
        numeric_value = _parse_numeric(text_value)
        if numeric_value is not None:
            epoch = numeric_value
            if epoch == 0:
                return None
            if abs(epoch) > 10**12:
                epoch /= 1000.0
            return datetime.fromtimestamp(epoch, tz=timezone.utc).date()
        parsed_date = _parse_date_string(text_value)
        if parsed_date is not None:
            return parsed_date
    return value


def _normalize_boolean_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return bool(int(value))
        return value
    if isinstance(value, str):
        text_value = value.strip().lower()
        if text_value == "":
            return None
        if text_value in {"1", "true", "t", "yes", "y"}:
            return True
        if text_value in {"0", "false", "f", "no", "n"}:
            return False
    return value


def _normalize_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        text_value = value.strip()
        if text_value == "":
            return None
        try:
            return json.loads(text_value)
        except json.JSONDecodeError:
            return value
    return value


def _is_nullable_foreign_key(column: Any) -> bool:
    return bool(column.nullable and column.foreign_keys)


def _normalize_nullable_fk_sentinel(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if float(value) == 0.0:
            return None
        return value
    if isinstance(value, str):
        text_value = value.strip()
        if text_value == "":
            return None
        numeric_value = _parse_numeric(text_value)
        if numeric_value is not None and numeric_value == 0.0:
            return None
        return value
    return value


def _parse_numeric(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _parse_datetime_string(value: str) -> datetime | None:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_date_string(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        parsed_dt = _parse_datetime_string(value)
        if parsed_dt is None:
            return None
        return parsed_dt.date()


def _is_foreign_key_violation(exc: Exception) -> bool:
    if _extract_sqlstate(exc) == "23503":
        return True

    current: object | None = exc
    while current is not None:
        if current.__class__.__name__ == "ForeignKeyViolation":
            return True
        current = getattr(current, "orig", None)

    if isinstance(exc, IntegrityError):
        return "foreign key" in str(exc).lower()
    return False


def _is_invalid_boolean_value_error(exc: Exception) -> bool:
    sqlstate = _extract_sqlstate(exc)
    if sqlstate == "22P02" and "boolean" in str(exc).lower():
        return True

    return "is not none, true, or false" in str(exc).lower()


def _classify_skippable_row_error(exc: Exception) -> str | None:
    if _is_foreign_key_violation(exc):
        return "mapped_table_fk_missing_parent"
    if _is_invalid_boolean_value_error(exc):
        return "mapped_table_invalid_boolean"
    return None


def _extract_sqlstate(exc: Exception) -> str | None:
    current: object | None = exc
    while current is not None:
        value = getattr(current, "sqlstate", None) or getattr(current, "pgcode", None)
        if isinstance(value, str) and value.strip():
            return value
        current = getattr(current, "orig", None)
    return None


def _stream_name(src_table: str) -> str:
    return f"table:{src_table}"


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        try:
            return int(text_value)
        except ValueError:
            return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _quote_mysql_ident(identifier: str) -> str:
    escaped = identifier.replace("`", "``")
    return f"`{escaped}`"


def _get_source_columns(
    *,
    source_conn: Connection,
    src_table: str,
    cache: dict[str, set[str]],
) -> set[str]:
    if src_table in cache:
        return cache[src_table]
    inspector = inspect(source_conn)
    try:
        columns = {
            str(item["name"])
            for item in inspector.get_columns(src_table)
            if item.get("name") is not None
        }
    except SQLAlchemyError:
        columns = set()
    cache[src_table] = columns
    return columns


def _ensure_source_system(
    *,
    session: Session,
    server_name: str,
    cloud_num: int,
) -> int:
    existing = session.scalar(
        select(SourceSystem).where(
            SourceSystem.server_name == server_name,
            SourceSystem.cloud_num == cloud_num,
        )
    )
    if existing is not None:
        return int(existing.id)

    source_system = SourceSystem(
        server_name=server_name,
        cloud_num=cloud_num,
        status="active",
    )
    session.add(source_system)
    session.commit()
    session.refresh(source_system)
    return int(source_system.id)


def _stream_cursor(
    *,
    session: Session,
    source_system_id: int,
    stream_name: str,
) -> int:
    state = session.scalar(
        select(SyncState).where(
            SyncState.source_system_id == source_system_id,
            SyncState.stream_name == stream_name,
        )
    )
    if state is None or state.last_cursor is None:
        return 0
    return int(state.last_cursor)


def _upsert_stream_state(
    *,
    session: Session,
    source_system_id: int,
    stream_name: str,
    last_cursor: int,
) -> None:
    stmt = pg_insert(SyncState).values(
        source_system_id=source_system_id,
        stream_name=stream_name,
        last_cursor=last_cursor,
        last_synced_at=datetime.now(timezone.utc),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SyncState.source_system_id, SyncState.stream_name],
        set_={
            "last_cursor": last_cursor,
            "last_synced_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        },
    )
    session.execute(stmt)


def _record_sync_error(
    *,
    session: Session,
    sync_run_id: int,
    source_system_id: int,
    stream_name: str,
    entity_key: str | None,
    error_code: str,
    error_message: str,
    payload_fragment: dict[str, Any] | None,
) -> None:
    session.add(
        SyncError(
            sync_run_id=sync_run_id,
            source_system_id=source_system_id,
            stream_name=stream_name,
            entity_key=entity_key,
            error_code=error_code,
            error_message=error_message,
            payload_fragment=payload_fragment,
        )
    )


def run_toon_lahmajo_mapped_table_sync(
    *,
    server_name: str | None = None,
    cloud_num: int | None = None,
    batch_size: int | None = None,
    max_batches_per_table: int | None = None,
    include_tables: tuple[str, ...] | None = None,
    exclude_tables: tuple[str, ...] | None = None,
) -> MappedSyncRunSummary:
    return ToonLahmajoMappedTableSync().run(
        server_name=server_name,
        cloud_num=cloud_num,
        batch_size=batch_size,
        max_batches_per_table=max_batches_per_table,
        include_tables=include_tables,
        exclude_tables=exclude_tables,
    )
