FROM python:3.11-slim

WORKDIR /app

# Install uv for rapid package installations
RUN pip install --no-cache-dir uv

# Copy project files and lockfile
COPY pyproject.toml uv.lock ./

# Synchronize dependencies frozen
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Start uvicorn server. Render (and most PaaS hosts) assign the port to
# listen on via the $PORT env var at runtime — it is not known at build
# time and changes between deploys, so it cannot be hardcoded. Shell form
# is required here (not the ["..."] exec form) so $PORT actually expands;
# falls back to 2323 for local `docker run` without Render's env injected.
CMD ["sh", "-c", "uv run uvicorn main:app --host 0.0.0.0 --port ${PORT:-2323}"]
