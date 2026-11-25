# PathPilot AI backend (FastAPI) — deploy image for Railway / Render / Fly.io.
# Build from the REPO ROOT:  docker build -f backend/Dockerfile .
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/ai ./ai
COPY backend/domain ./domain
COPY data /data
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
