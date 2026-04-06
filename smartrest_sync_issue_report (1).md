# SmartRest Sync Issue Report

## Overview

This document explains the data sync failure observed while syncing data from the source MariaDB database (`toon_lahmajo`) into the target PostgreSQL database (`smartrest`).

The issue was initially visible as:

- `rows_processed: 0` for some sync steps even though the source database had data
- `partial` sync runs for `branch` and `profiles`
- foreign key failures while inserting into `orders`
- timestamp type conversion errors during upsert

This report covers:

1. The symptoms that were observed
2. The confirmed root causes
3. Why the current behavior happens
4. The recommended general solution
5. Immediate next steps for implementation

---

## Confirmed Symptoms

### 1. Target tables were empty

The target PostgreSQL database had:

- `branches` table present, but with `0` rows
- `orders` table present, but with `0` rows

At the same time, the source MariaDB database was not empty:

- `branch` had `1` row
- `profiles` had `2` rows

This proved that the problem was not “missing source data.”

### 2. Some sync steps reported success but processed 0 rows

Examples:

- `make sync-toon-smartrest-step table=branch batch=500`
- `make sync-toon-smartrest-step table=profiles batch=500`

These initially returned `success` with `rows_processed: 0`, even though the target tables were empty.

### 3. Full sync later failed on foreign keys

When the full sync reached `orders`, PostgreSQL rejected inserts like this:

- foreign key constraint `fk_orders_branch_id_branches`
- `branch_id = 1` was not present in `branches`

This meant child rows were being inserted before the required parent rows existed in the target database.

### 4. Branch and profiles sync runs were later marked partial

After resetting and rerunning, the sync no longer silently skipped data. Instead, `branch` and `profiles` runs returned `partial`, which showed that inserts were actually failing.

### 5. Type conversion errors were confirmed in sync_errors

The exact error recorded for `branch` was:

- integer value sent into `branches.created_at`
- target column expected `timestamp with time zone`

The exact error recorded for `profiles` was similar:

- integer values sent into `profiles.billing_start_time` / `billing_end_time`
- target columns expected `timestamp with time zone`

Example values seen in the payload:

- `1683819710`
- `1616411629`

These are Unix epoch timestamps stored as integers in the source DB.

---

## Confirmed Root Causes

There are **two distinct root causes**.

### Root Cause 1: Stale sync cursor/state after recreating the target DB

The sync process is incremental and stores cursor state in `sync_state`.

Relevant tables found in PostgreSQL:

- `sync_state`
- `sync_runs`
- `sync_errors`
- `fifo_state`

The `sync_state` table contained rows like:

- `table:branch` with `last_cursor = 1`
- `table:profiles` with `last_cursor = 376`

That means the sync engine believed these streams were already processed, even though the target tables had been recreated and were empty.

So the system had this mismatch:

- target DB was fresh / empty
- sync cursor state was old / advanced

Result:

- the sync skipped rows it should have reloaded
- parent tables remained empty
- downstream tables later failed

### Root Cause 2: Generic mapped sync does not normalize source values to target types

The source database stores several timestamp-like values as `bigint` integers.

For example:

- `branch.created_at` is `bigint`
- `profiles.billing_start_time` is `bigint`
- `profiles.billing_end_time` is `bigint`

The target PostgreSQL schema expects these fields as:

- `timestamp with time zone`

The mapped sync currently passes raw integers directly into PostgreSQL upserts.

That causes errors like:

- `cannot cast type integer to timestamp with time zone`

A related issue was also seen in `orders`:

- empty string `""` was passed into a timestamp column
- PostgreSQL rejected it as invalid timestamp syntax

So the sync currently lacks a robust normalization layer for type mismatches.

---

## Why This Happens

The mapped sync is cursor-based.

The general flow is:

1. Read rows from source DB using a cursor (`WHERE id > :cursor`)
2. Transform rows into an upsert payload
3. Insert/upsert into target PostgreSQL
4. Store new `last_cursor` in `sync_state`

This design is fine, but it assumes:

- the target DB still contains previously synced data
- source values are already compatible with target column types

In this case, both assumptions were false:

- the target was recreated, so the data was gone
- the source contained integer epoch values and empty-string timestamps

That combination creates a confusing failure mode:

- old cursor state causes rows to be skipped
- resetting the cursor reveals insert failures
- failed parent-table loads cause downstream foreign-key errors

---

## Recommended Solution

The correct solution is **not** to patch one table at a time.

This should be handled as a **general sync normalization problem**.

### Recommended strategy

Implement a **centralized normalization layer** in the generic mapped sync path.

This layer should:

1. Look at the **target column type**
2. Normalize the source value before upsert
3. Apply generic conversions automatically
4. Allow per-column overrides for edge cases

This is the scalable approach because the same mismatch pattern is likely to appear in many tables:

- `created_at`
- `updated_at`
- `start_time`
- `end_time`
- `*_date`
- similar fields stored as integers or empty strings in MySQL/MariaDB

---

## Detailed Design Recommendation

### 1. Normalize values centrally before insert/upsert

Do not hardcode conversions only for `branch` or `profiles`.

Instead, in the mapped sync pipeline, normalize every outgoing value using the **target column type**.

Suggested behavior:

#### For timestamp / timestamptz target columns

- `None` -> `None`
- `""` -> `None`
- integer / bigint / float epoch -> convert to timezone-aware `datetime`
- already a `datetime` -> keep as-is
- string timestamp -> parse if valid

#### For date target columns

- `None` or `""` -> `None`
- parse valid string/date values to `date`

#### For boolean target columns

- normalize `0/1`, `"0"/"1"`, `"true"/"false"`

#### For JSON / JSONB target columns

- parse JSON strings when needed

#### For everything else

- pass through unchanged

### 2. Use target schema metadata, not only column names

A column-name heuristic is helpful but should not be the main logic.

For example:

- `created_at`
- `updated_at`
- `billing_start_time`
- `billing_end_time`

These names suggest timestamp fields, but the safer rule is:

- inspect the target SQLAlchemy column type, or
- inspect target PostgreSQL schema metadata and cache it

That way, conversions are based on what the target **actually expects**, not only what the source column is called.

### 3. Keep per-column overrides for exceptions

Even with generic normalization, some fields may need custom handling.

For example:

- seconds vs milliseconds epoch
- `0` used as “unset”
- sentinel values
- weird legacy formats

So the generic normalizer should support per-column overrides such as:

- `("branch", "created_at") -> epoch_to_timestamptz`
- `("profiles", "billing_start_time") -> epoch_to_timestamptz`
- `("profiles", "billing_end_time") -> epoch_to_timestamptz`

### 4. Validate rows before upsert

Currently, PostgreSQL rejects bad values at insert time.

That is useful, but too late.

A better design is to validate normalized row payloads before executing the upsert.

When validation fails, log:

- stream name
- entity key
- column name
- source value
- source Python type
- expected target type
- normalization attempt

That will make sync errors far easier to diagnose.

### 5. Handle empty strings for timestamp/date fields

This must be part of the same solution.

`""` should become `NULL` / `None` for date and timestamp targets.

This is important because at least one failure already showed invalid empty-string timestamp input in `orders`.

---

## Suggested Python Normalization Logic

A minimal starting point:

```python
from datetime import datetime, timezone


def normalize_value(value, target_type_name: str):
    if value in (None, ""):
        return None

    t = target_type_name.lower()

    if t in {"timestamp", "timestamptz", "datetime", "timestamp with time zone"}:
        if isinstance(value, (int, float)):
            # optional support for milliseconds-based epochs
            if value > 10**12:
                value = value / 1000
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return value

    return value
```

And for the exact conversion behavior you already need:

```python
from datetime import datetime, timezone


def normalize_timestamptz(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return value
```

This should be integrated into the generic mapped sync code, not only used in one table-specific function.

---

## Immediate Implementation Plan

### Step 1. Patch mapped sync normalization

In the generic mapped sync path:

- inspect destination columns
- normalize outgoing payload values before building upsert rows
- support epoch integer -> UTC datetime
- support empty string -> `None`

### Step 2. Add logging for normalized fields

At least temporarily, log which fields were normalized so testing is easier.

### Step 3. Reset mapped sync state

After the code is fixed, reset the mapped sync cursor state for the table streams.

A minimal reset is safer than wiping everything:

```sql
DELETE FROM sync_state
WHERE source_system_id = 1
  AND stream_name LIKE 'table:%';
```

This avoids keeping stale cursors for mapped tables.

### Step 4. Rerun in dependency order

Rerun in this order:

1. `branch`
2. confirm `branches` has rows
3. `profiles`
4. confirm `profiles` has rows
5. full sync

This order matters because downstream tables depend on parent tables.

### Step 5. Re-check foreign key failures

Once `branches` is actually loaded, the `orders.branch_id` FK problem should either:

- disappear, or
- reveal the next real issue

At that point, if `orders` still fails, the next likely blocker will be another normalization issue such as empty string timestamps.

---

## Useful Debug Queries

### PostgreSQL: confirm target table row counts

```sql
SELECT count(*) FROM branches;
SELECT count(*) FROM profiles;
SELECT count(*) FROM orders;
```

### PostgreSQL: inspect sync state

```sql
SELECT *
FROM sync_state
ORDER BY updated_at DESC;
```

### PostgreSQL: inspect sync errors

```sql
SELECT id, sync_run_id, stream_name, entity_key, error_code, error_message, occurred_at
FROM sync_errors
ORDER BY id DESC;
```

### MariaDB / phpMyAdmin: inspect source column types

```sql
SELECT
  TABLE_NAME,
  COLUMN_NAME,
  COLUMN_TYPE,
  DATA_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
ORDER BY TABLE_NAME, ORDINAL_POSITION;
```

### MariaDB / phpMyAdmin: audit likely timestamp-like integer fields

```sql
SELECT
  TABLE_NAME,
  COLUMN_NAME,
  COLUMN_TYPE,
  DATA_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND DATA_TYPE IN ('bigint', 'int', 'tinyint')
  AND (
    COLUMN_NAME LIKE '%created_at%' OR
    COLUMN_NAME LIKE '%updated_at%' OR
    COLUMN_NAME LIKE '%start_time%' OR
    COLUMN_NAME LIKE '%end_time%' OR
    COLUMN_NAME LIKE '%date%'
  )
ORDER BY TABLE_NAME, COLUMN_NAME;
```

This is useful for identifying other source fields that may need normalization.

---

## Final Conclusion

The current sync issue is caused by a combination of:

1. **stale incremental sync state** after recreating the target database
2. **missing generic type normalization** in the mapped sync pipeline

The immediate blockers are:

- `branch.created_at` stored as `bigint` epoch in source, but expected as `timestamptz` in target
- `profiles.billing_start_time` / `billing_end_time` stored as integer epochs in source, but expected as `timestamptz` in target
- empty-string timestamp values in downstream tables such as `orders`

The recommended fix is:

- implement centralized schema-driven normalization in the generic sync path
- support epoch integer to UTC datetime conversion
- support empty string to `NULL` conversion for date/timestamp columns
- keep per-column overrides for exceptional fields
- reset mapped sync state only after the normalization patch is in place

This solution is scalable and prevents the same class of issue from reappearing in other tables.
