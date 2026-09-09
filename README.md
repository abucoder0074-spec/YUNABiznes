# YUNABiznes — inventory and purchasing foundation

YUNABiznes is the backend foundation for a local ice-cream manufacturer's raw-material operations. It records incoming materials, warehouse movements, production consumption, supplier returns, supplier debt, and the audit trail required to trust those records. It deliberately has no sales, frontend, Telegram, Excel-export, or CRUD implementation yet.

## Architecture

The FastAPI application lives in `backend/app`. PostgreSQL is the source of truth, SQLAlchemy 2.x uses typed asynchronous models, and Alembic owns the versioned schema.

Key accounting design choices:

- Inventory is calculated from append-only `inventory_transactions`; there is no mutable `product.stock` field.
- Quantities and money use `NUMERIC` mapped to Python `Decimal`, never `float`.
- Purchases contain items; payment allocations can target a purchase or remain an unallocated supplier credit.
- Supplier debt is the net of immutable `supplier_ledger` debit and credit events, not a manually editable total.
- Line totals are database-generated (`quantity * unit_price`) so they cannot diverge from their inputs.
- Inventory transactions, supplier ledger entries, and audit logs cannot be updated or deleted through the ORM. Historical documents have draft/posted/void states instead.
- `post_production_issue` is a transaction-safe foundation workflow: it locks existing movements, calculates stock, rejects oversupply, and writes its issue, inventory events, and audit event together.

## Project layout

```text
backend/
  alembic/                 Versioned PostgreSQL schema
  app/
    api/                   Health-only API foundation
    core/                  Configuration and enums
    db/                    Async engine, sessions, declarative base
    models/                Typed SQLAlchemy entities
    repositories/          Inventory balance queries
    schemas/               Pydantic response schemas
    services/              Transaction-safe domain workflows
  tests/                   Async model, DB, and service tests
```

## Local setup

1. Create a virtual environment and install dependencies:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r backend\requirements.txt
   ```

2. Copy `.env.example` to `.env` and replace `POSTGRES_PASSWORD` and the matching password in `DATABASE_URL` with a strong local secret.

3. Start PostgreSQL:

   ```powershell
   docker compose up -d db
   ```

4. Apply the schema migration:

   ```powershell
   cd backend
   alembic upgrade head
   ```

5. Run FastAPI:

   ```powershell
   uvicorn app.main:app --reload
   ```

   `GET http://127.0.0.1:8000/health` returns the running environment without exposing secrets.

## QUICK START — WINDOWS

Install and configure PostgreSQL once, then configure the root `.env` once. After that,
double-click `start.bat` from the repository root. The startup script verifies the
`.venv`, PostgreSQL on `localhost:5432`, the `.env` file, and `DATABASE_URL`, checks
database connectivity, runs `alembic upgrade head`, starts the backend, and starts a
frontend automatically if a `frontend\package.json` exists.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Set the real PostgreSQL password in `.env` without committing it. Then use:

- `start.bat` — start YUNABiznes and open the backend docs (or frontend).
- `stop.bat` — stop only the YUNABiznes processes recorded by the startup script.
- `restart.bat` — stop and start YUNABiznes again.

Logs are written to `logs\backend.log`, `logs\backend.error.log`, and
`logs\startup.log`. Passwords are not printed by the scripts.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Async SQLAlchemy connection URL; production/local Docker uses `postgresql+asyncpg://…`. |
| `POSTGRES_DB` | PostgreSQL database initialized by Docker. |
| `POSTGRES_USER` | PostgreSQL role initialized by Docker. |
| `POSTGRES_PASSWORD` | PostgreSQL password initialized by Docker. Keep it out of Git. |
| `APP_ENV` | Runtime label such as `development`, `test`, or `production`. |

SQLite via `sqlite+aiosqlite://` is accepted only for the isolated automated tests; application operation and migrations target PostgreSQL.

## Developer commands

From the repository root:

```powershell
make install
make db-up
make migrate
make run
make test
make lint
```

On Windows without `make`, use the individual commands in the setup section and run tests from `backend` with `pytest`.

## Migration workflow

The initial schema is revision `20260907_0001`. Subsequent schema changes must be represented by new Alembic revisions; do not change an applied migration or maintain accounting balances with ad hoc SQL. Create a new revision with:

```powershell
cd backend
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```
