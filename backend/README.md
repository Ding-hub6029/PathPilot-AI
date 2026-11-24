# Backend

Day-1 FastAPI backend. Rules/template mode needs no AI key.

## Run

```bash
cd backend
python -m venv .venv   # or reuse the project .venv at the repo root
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

From the repo root the same server is:

```bash
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

## Endpoints (all under /api/v1)

- `GET /health`, `GET /ready`
- `GET /programs`, `GET /programs/{id}` (2 real programs; fixtures refused at startup)
- `POST /profile/validate`, `POST /match`, `POST /explain`, `POST /simulate`
- Track mismatch returns 422 `TRACK_MISMATCH`.
- Errors: `{error:{code,message,field_errors,retryable},request_id}`.
- CORS: `http://localhost:3000` only.
