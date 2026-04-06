# Runtime Setup

## Local Python
1. Create virtual environment:
   - `python3 -m venv .venv`
2. Install dependencies:
   - `.venv/bin/pip install -r requirements.txt`
3. Run app:
   - `.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`

## Docker Compose
1. Copy env template:
   - `cp .env.example .env`
   - Set `SMARTREST_DATABASE_URL` for the operational DB.
   - Set `SMARTREST_CHAT_ANALYTICS_DATABASE_URL` for the chat analytics DB.
   - Set `TOON_LAHMAJO_DB` for source sync extraction.
   - Optional sync tuning:
     - `SMARTREST_SYNC_BATCH_SIZE_TABLES` (default `1000`)
   - Optional mode toggles:
     - `SMARTREST_SCOPE_BACKEND_MODE` (`mock`, `db_with_fallback`, `db_strict`)
     - `SMARTREST_REPORT_BACKEND_MODE` (`mock`, `db_with_fallback`, `db_strict`)
2. Start app service:
   - `docker compose up --build`
3. Optional: start Postgres profile too:
   - `docker compose --profile db up --build`

## Controlled Sync Steps
- Full mapped-table sync:
  - `make sync-toon-smartrest`
- One-batch, one-table step sync (safer for large sources):
  - `make sync-toon-smartrest-step table=profiles_room_table_order batch=500`
