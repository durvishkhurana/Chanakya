# One container for the hosted demo (Render): the FastAPI backend on 127.0.0.1:8000 behind the Next.js server
# on $PORT (7860 by default), which proxies /api (REST and WebSockets) to it. Keys come from the host's secrets.
FROM node:20-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Baked into the rewrites at build time.
ENV NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev

FROM python:3.12-slim-bookworm
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
RUN useradd -m -u 1000 user
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY --chown=user . .
COPY --from=frontend --chown=user /app/frontend /app/frontend
# /app itself stays root-owned; the ledger and run logs write under .state.
RUN mkdir -p .state && chown user .state
USER user

# Public demo: missions and dashboards on, laptop-only demo tools, email and phone calls off.
ENV PYTHONUNBUFFERED=1 NODE_ENV=production \
    MISSIONS_ENABLED=true PLANNER_ENABLED=true COACH_ENABLED=true WINBACK_ENABLED=true CALLING_HOURS=0-24 \
    DEMO_TOOLS_ENABLED=false LINK_EMAIL_ENABLED=false TWILIO_ENABLED=false
EXPOSE 7860
# shortcut: no process supervisor, so a crashed backend leaves the page up with API errors; restart the Space.
CMD ["sh", "-c", "python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 & cd frontend && exec node node_modules/next/dist/bin/next start -H 0.0.0.0 -p ${PORT:-7860}"]
