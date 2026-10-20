FROM python:3.11-slim

WORKDIR /app

# Install uv for rapid package installations
RUN pip install --no-cache-dir uv

# Build from the repository root; the lockfile describes a uv workspace.
# Keep the environment outside the source bind mount used by Compose.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app/backend:/app"
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/README.md ./backend/
RUN uv sync --frozen --all-packages --no-dev
COPY backend ./backend
COPY ingestion ./ingestion
COPY widget ./widget
COPY admin/dist ./admin/dist
WORKDIR /app/backend

# Start uvicorn server. Render (and most PaaS hosts) assign the port to
# listen on via the $PORT env var at runtime — it is not known at build
# time and changes between deploys, so it cannot be hardcoded. Shell form
# is required here (not the ["..."] exec form) so $PORT actually expands;
# falls back to 2323 for local `docker run` without Render's env injected.
CMD ["sh", "-c", "exec python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-2323}"]
