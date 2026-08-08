## Install the project

  From the repository root:

  cd "/Users/amirhesam_ghahari/Desktop/Intelligent Ticket Price Tracker"

  python3 -m venv .venv
  source .venv/bin/activate

  python3 -m pip install --upgrade pip
  python3 -m pip install -e .

  This installs the dependencies from pyproject.toml and installs your package in editable mode.

  Create configuration:

  cp .env.example .env

  Then edit .env and set the correct PostgreSQL connection string.

  To build a distributable package:

  python3 -m pip install build
  python3 -m build

  The generated package files will appear in dist/.

  After PostgreSQL is running and migrations are restored:

  alembic upgrade head
  run-pipeline --stage stage1 \
    --file sample_data/brightdata_fb-market-scraper.json

  Your current python3 is Python 3.14.6, which satisfies the project requirement of Python 3.12 or newer.


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


### 2. Start local PostgreSQL

  Check which PostgreSQL version Homebrew has installed:

  brew list --versions | grep postgresql

  Start it, for example:

  brew services start postgresql@16

  Or, if the unversioned package is installed:

  brew services start postgresql

  Create the database:

  createdb ticket_tracker

  If that fails, try:

  psql postgres

  Then inside PostgreSQL:

  CREATE DATABASE ticket_tracker;
  \q