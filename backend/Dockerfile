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

# Start uvicorn server
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "2323"]
