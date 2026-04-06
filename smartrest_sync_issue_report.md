# SmartRest sync issue report

## Summary

The sync problem is **not** caused by Docker, Postgres startup, or a missing source table.

The actual failure is in the **data mapping layer** during the MariaDB → Postgres sync:

- source table `branch.created_at` is stored as a **BIGINT** in MariaDB
- target table `branches.created_at` is stored as a **timestamp with time zone** in Postgres
- the sync currently sends the raw integer value directly into Postgres
- Postgres rejects it with a cast error
- because `branches` does not get populated, later inserts into `orders` fail on the foreign key `branch_id -> branches.id`

There was also a secondary issue:

- `sync_state` contained old cursor values even though the new target database was empty
- this caused some sync steps to report `rows_processed: 0`
- after resetting/retrying, the real data-type conversion problem became visible

---

## Symptoms observed

### 1. Postgres container originally failed to start

The Postgres 18 container initially failed because the volume layout was from an older Postgres image.

Error indicated:

- old data existed in `/var/lib/postgresql/data`
- Postgres 18 expects the new layout under `/var/lib/postgresql`

This was fixed by changing the Compose volume mount for the Postgres 18 container.

---

### 2. Pytest could not connect

Pytest initially failed with:

- missing Python package `psycopg`
- later, `connection refused` to `127.0.0.1:5433`

That happened because the Postgres container was not healthy at that time.

Once Postgres was running, migrations worked.

---

### 3. Sync commands returned success with zero processed rows

Examples:

- `make sync-toon-smartrest-step table=branch batch=500`
- `make sync-toon-smartrest-step table=profiles batch=500`

They returned success or partial success, but target tables were still empty.

This was suspicious because:

- source MariaDB contained data
- target Postgres tables were empty

---

### 4. Full sync later failed on foreign keys

Postgres logs showed errors like:

- `insert or update on table "orders" violates foreign key constraint "fk_orders_branch_id_branches"`
- `Key (branch_id)=(1) is not present in table "branches"`

This means:

- sync tried to insert `orders`
- but parent row in `branches` was missing
- so `orders` could not be inserted

---

### 5. Sync error table exposed the real root cause

The most important error rows were:

- `table:branch -> mapped_table_upsert_failed`
- `table:profiles -> mapped_table_upsert_failed`

The actual Postgres error was:

`cannot cast type integer to timestamp with time zone`

Examples from the failing payload:

- `branches.created_at = 1683819710`
- `profiles.billing_start_time = 1616411629`

These are Unix epoch integer values, not proper timestamp objects.

---

## Database facts confirmed during debugging

### Target Postgres

Confirmed:

- table `branches` exists
- table `orders` exists
- `branches` row count was `0`
- `orders` row count was `0`

### Source MariaDB

Confirmed:

- source table `branch` row count was `1`
- source table `profiles` row count was `2`

### Sync state

`sync_state` contained existing cursors such as:

- `table:branch -> last_cursor = 1`
- `table:profiles -> last_cursor = 376`

This proves the sync engine believed those streams had already been processed, even though the target tables were empty.

---

## Root cause

## Primary root cause

The sync mapping does not convert epoch integer fields to Python/Postgres timestamp values before insert.

### What is happening

Example:

- source value: `1683819710`
- source DB type: `BIGINT`
- target DB type: `TIMESTAMP WITH TIME ZONE`

Current behavior:

- raw integer is passed into the SQLAlchemy/Postgres insert

Result:

- Postgres throws `cannot cast type integer to timestamp with time zone`

Affected fields observed so far:

- `branch.created_at -> branches.created_at`
- `profiles.billing_start_time -> profiles.billing_start_time`
- `profiles.billing_end_time -> profiles.billing_end_time`

Likely there are more timestamp-like fields in other mapped tables.

---

## Secondary root cause

The target Postgres database was recreated/reset, but the sync cursor metadata was still present in `sync_state`.

This caused the sync runner to skip rows or behave as if earlier data was already synced.

So there were actually **two issues**:

1. stale sync cursors/state
2. broken timestamp conversion in mapped sync

The stale state caused confusion.
The timestamp conversion bug is the main reason inserts fail.

---

## Why `orders` fails even though `orders` is not the first broken table

`orders` depends on parent records such as `branches`.

Because `branches` fails first, no parent row is inserted.

Then when `orders` tries to insert a row with `branch_id = 1`, Postgres rejects it because:

- `branches.id = 1` does not exist

So the `orders` foreign-key error is **downstream**, not the original cause.

---

## Recommended solution

## 1. Fix timestamp normalization in the sync code

Wherever the mapped payload is built before insert/upsert, convert epoch integers to timezone-aware datetimes.

### Suggested helper

```python
from datetime import datetime, timezone


def normalize_timestamptz(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return value
```

### Apply it to fields like

- `created_at`
- `billing_start_time`
- `billing_end_time`
- any other source field stored as epoch integer but written to Postgres timestamp columns

---

## 2. Treat empty-string timestamps as `NULL`

Another Postgres error already appeared during sync:

- `invalid input syntax for type timestamp with time zone: ""`

That means some source rows contain an empty string for a timestamp-like field.

Required behavior:

- `""` should become `None`
- do **not** pass empty strings to Postgres timestamp columns

---

## 3. Reset sync cursor state for a fresh local target database

Because the local Postgres database was recreated, the sync metadata should also be reset.

### Safer targeted reset

```sql
DELETE FROM sync_state
WHERE source_system_id = 1
  AND stream_name LIKE 'table:%';
```

This removes mapped-table cursors without wiping everything else.

### More aggressive local-only reset

Use only if this local target DB is disposable:

```sql
TRUNCATE TABLE sync_state, sync_runs, sync_errors RESTART IDENTITY;
```

---

## 4. Rerun sync in dependency order

After code fix + state reset:

1. sync `branch`
2. verify `branches` now has rows
3. sync `profiles`
4. run full sync

Suggested order:

```bash
make sync-toon-smartrest-step table=branch batch=500
make sync-toon-smartrest-step table=profiles batch=500
make sync-toon-smartrest
```

---

## Validation checklist

After patching, verify these points.

### Branch table

```sql
SELECT count(*) FROM branches;
```

Expected:

- count should become greater than `0`

### Profiles table

```sql
SELECT count(*) FROM profiles;
```

Expected:

- count should become greater than `0`

### Sync errors

```sql
SELECT id, sync_run_id, stream_name, error_code, error_message
FROM sync_errors
ORDER BY id DESC
LIMIT 20;
```

Expected:

- no new `cannot cast type integer to timestamp with time zone` errors
- no new timestamp empty-string errors

### Orders

```sql
SELECT count(*) FROM orders;
```

Expected:

- orders should start loading once parent tables are present and timestamp conversion issues are fixed

---

## Useful diagnostic SQL

### Postgres: see table columns and types

```sql
SELECT column_name, data_type, udt_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'branches';
```

### MariaDB / phpMyAdmin: inspect source column type

```sql
SELECT 
  COLUMN_NAME,
  COLUMN_TYPE,
  DATA_TYPE,
  IS_NULLABLE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'toon_lahmajo'
  AND TABLE_NAME = 'branch'
  AND COLUMN_NAME = 'created_at';
```

### Check sync cursors

```sql
SELECT *
FROM sync_state
ORDER BY updated_at DESC;
```

### Check recent sync errors

```sql
SELECT id, sync_run_id, stream_name, entity_key, error_code, error_message, occurred_at
FROM sync_errors
ORDER BY id DESC
LIMIT 50;
```

---

## Final conclusion

The sync failure is caused by a **mapping/type-conversion bug**:

- source stores timestamp-like values as epoch `BIGINT`
- target expects `TIMESTAMP WITH TIME ZONE`
- sync passes raw integers instead of converted datetimes

This prevents parent tables such as `branches` and `profiles` from loading.
Because those parent tables stay empty, downstream tables such as `orders` fail on foreign-key constraints.

The permanent fix is:

1. normalize epoch integers to Python datetimes before upsert
2. normalize empty string timestamps to `NULL`
3. reset stale sync state when using a fresh local target database
4. rerun sync in dependency order

---

## Suggested next implementation task

Add a reusable timestamp-normalization step in the mapped sync pipeline, ideally at the point where source row values are transformed into the upsert payload, so every mapped table benefits automatically instead of patching fields one by one.
