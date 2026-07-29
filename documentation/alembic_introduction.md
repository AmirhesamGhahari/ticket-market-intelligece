# Alembic — Introduction & Reference

## What is Alembic?

Alembic is a database migration tool for SQLAlchemy. The simplest way to think about it: **git for your database schema**.

- Your Python ORM models describe what the tables *should* look like
- Migration files are numbered scripts that transform the database from one state to the next
- Alembic tracks which migrations have already run by storing the current revision ID in a special table called `alembic_version` that it creates automatically in your database
- Running migrations is safe to repeat — if everything is already up to date, Alembic does nothing

---

## The Key Files

| File | Purpose |
|---|---|
| `alembic.ini` | Config file — tells Alembic where its folder lives, logging setup |
| `alembic/env.py` | The bridge — connects Alembic to your app's database URL and ORM models |
| `alembic/script.py.mako` | Template used when generating new migration files — never edit this |
| `alembic/versions/` | Folder containing all migration scripts |

---

## How the Migration Chain Works

Each migration file has two key variables:

```python
revision: str = "b2c3d4e5f6a1"       # this file's unique ID
down_revision: Union[str, None] = "a1b2c3d4e5f6"  # the file before this one
```

Alembic reads all files in `versions/` and builds a linked chain from these values — not from the filenames. `down_revision = None` means "this is the first migration, nothing before it."

```
None → a1b2c3d4e5f6 → b2c3d4e5f6a1
       (0001)          (0002)
```

When you run `alembic upgrade head`, it finds where you currently are in the chain (stored in `alembic_version`) and replays every migration after that point in order.

---

## Manual vs Autogenerate

### What we did (manual)

Every `op.create_table(...)` and `op.create_index(...)` in our migration files was written by hand. This works but risks drifting out of sync with the ORM models — which is exactly what happened (FK constraints and indexes existed in migrations but not in the ORM models until we fixed them).

### Autogenerate (the right way going forward)

When you run `alembic revision --autogenerate`, Alembic:

1. Reads your ORM models via `Base.metadata` (every model that inherits from `Base` is registered there)
2. Connects to the live database and reads what actually exists
3. Computes the **diff** — what's in your models but not in the database, and vice versa
4. Writes a migration file for exactly that difference

This means:
- If the database is empty → generates `CREATE TABLE` for all your tables
- If you add a new column to an ORM model → generates `ALTER TABLE ... ADD COLUMN`
- If you remove a column → generates `ALTER TABLE ... DROP COLUMN`

**Critical requirement for autogenerate to work:** All constraints and indexes must be declared in the ORM model's `__table_args__`. If a `ForeignKeyConstraint` or `Index` only exists in a migration file but not in the ORM model, autogenerate will generate a migration to DROP it (because it looks like an unexpected leftover). This is why we keep ORM models and migrations in sync.

### What autogenerate gets right

- All tables — `CREATE TABLE` with correct column types, `nullable`, `server_default`
- `UniqueConstraint` and `Index` from `__table_args__`
- `ForeignKeyConstraint` from `__table_args__`
- New columns, dropped columns, type changes

### What autogenerate misses

- `onupdate=func.now()` — this is SQLAlchemy-only ORM behaviour, not a SQL clause. It doesn't appear in `CREATE TABLE` and autogenerate can't detect it. A Postgres-level equivalent would require a trigger.
- Python-side `default=` values (e.g. `default=uuid.uuid4`, `default=0`) — these don't exist at the Postgres level, so autogenerate correctly ignores them.

---

## Workflow: Starting Fresh (empty database)

```bash
# Delete existing manual migration files if starting over
rm alembic/versions/0001_create_pipeline_tables.py
rm alembic/versions/0002_create_veld_2026.py

# Generate migration from your ORM models
alembic revision --autogenerate -m "create initial schema"

# Always review the generated file before applying
cat alembic/versions/<generated_file>.py

# Apply to the database
alembic upgrade head
```

## Workflow: Adding or Changing a Model (ongoing development)

```bash
# 1. Edit the ORM model (e.g. add a new column to Veld2026Raw)
# 2. Generate a migration for just that change
alembic revision --autogenerate -m "add X column to veld_2026_raw"
# 3. Review the generated file
# 4. Apply it
alembic upgrade head
```

Never write migration SQL by hand after initial setup. Edit the ORM model — it is the source of truth — and let autogenerate translate the change into a migration file.

---

## CLI Command Reference

### Applying Migrations

```bash
# Apply all pending migrations (bring database to latest)
alembic upgrade head

# Apply exactly one migration forward
alembic upgrade +1

# Apply up to a specific revision
alembic upgrade b2c3d4e5f6a1
```

### Rolling Back

```bash
# Undo the last migration
alembic downgrade -1

# Undo the last two migrations
alembic downgrade -2

# Roll back to a specific revision
alembic downgrade a1b2c3d4e5f6

# Roll back everything (empty database)
alembic downgrade base
```

### Generating Migrations

```bash
# Generate a migration automatically by comparing ORM models to the database
alembic revision --autogenerate -m "describe what changed"

# Generate a blank migration file to write manually
alembic revision -m "describe what changed"
```

### Inspecting State

```bash
# Show the current revision the database is at
alembic current

# Show the full migration history (all revisions in order)
alembic history

# Show the full history with more detail
alembic history --verbose

# Show what migrations are pending (not yet applied)
alembic history -r current:head

# Show which revision is the latest (head)
alembic heads
```

### Inspecting SQL Without Running It

```bash
# Print the SQL that upgrade head would execute, without touching the database
alembic upgrade head --sql

# Print the SQL for a specific migration
alembic upgrade b2c3d4e5f6a1 --sql

# Print the SQL for rolling back one step
alembic downgrade -1 --sql
```

### Stamping (marking a revision without running migrations)

```bash
# Tell Alembic "the database is already at this revision" without running anything
# Useful when you create tables manually and want Alembic to start tracking from there
alembic stamp head

# Stamp a specific revision
alembic stamp a1b2c3d4e5f6
```

---

## What `alembic_version` Looks Like

After running `alembic upgrade head`, Postgres will have a table like this:

```
SELECT * FROM alembic_version;
 version_num
--------------
 b2c3d4e5f6a1
```

One row, one column — just the revision ID of the latest applied migration. Every `alembic upgrade` or `alembic downgrade` command updates this value. This is how Alembic knows where you are in the chain.

---

## Our Project's Migration Chain

```
down_revision=None
       │
       ▼
0001_create_pipeline_tables.py  (revision: a1b2c3d4e5f6)
  Creates: pipeline_runs, pipeline_errors
       │
       ▼
0002_create_veld_2026.py  (revision: b2c3d4e5f6a1)
  Creates: veld_2026_raw, veld_2026_transformed
```
