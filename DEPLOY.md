# PathPilot AI — Deploy the Day 2 preview

The app is **deploy-ready**. It is NOT live yet, because every free host
needs a platform login / OAuth authorisation that only Xiangfeng can grant.
No account was created, no money was spent, nothing was submitted.

## What needs Xiangfeng (one-time, ~10 minutes)

1. **Vercel (frontend)** — open the Vercel OAuth authorisation for Muse
   (the `vercel` connector reports `not_connected`) and approve it, or
   click the button below after the Day 2 code is pushed to GitHub:
   [![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/Ding-hub6029/PathPilot-AI)
   In the Vercel project settings set **Root Directory = `frontend`**.
2. **Backend host (Railway or Render free tier)** — create the project from
   the same GitHub repo and point it at `backend/Dockerfile`
   (Railway: "Deploy from Dockerfile"; Render: Web Service → Docker).
   No API key is needed by the app itself (rules/template mode).
3. **Connect the two** — in Vercel, set the environment variable
   `API_BASE_URL` to the backend's public URL (e.g.
   `https://pathpilot-backend.up.railway.app`), then redeploy the frontend.
   Locally this variable defaults to `http://localhost:8000`.

## What is already done

- Frontend builds cleanly (`npm run build`, locale check 6 × 138 keys).
- Backend serves 8 programmes on data version `v2` (`GET /api/v1/health`
  → `{"status":"ok","data_version":"v2","programs":8}`).
- The Next.js proxy (`frontend/next.config.js`) reads `API_BASE_URL` from
  the environment instead of a hardcoded localhost address.
- `backend/Dockerfile` builds the FastAPI service standalone
  (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`).
- No secrets are required: the AI explanation runs in rules/template mode
  (`ai_status=unavailable`) until an AI provider key is supplied by the user.

## Verify after deploy

- `GET <backend>/api/v1/health` → `data_version: "v2"`, `programs: 8`.
- Open the Vercel URL: home, wizard, results, a programme page and report
  all return 200; the wizard match call returns 8 programmes.
