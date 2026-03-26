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
2. Start app service:
   - `docker compose up --build`
3. Optional: start Postgres profile too:
   - `docker compose --profile db up --build`
