# Dockerfile multi-stage para {{PROJECT_NAME}} ({{STACK}})
# Target: imagen final < 200 MB con solo runtime + deps.

# ---------- Stage 1: builder ----------
# Python base. Si STACK=node, reemplazar "python:3.12-slim-bookworm" por "node:20-slim"
# y ajustar pip → npm.
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# System deps para compilar (removed en runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl git \
    && rm -rf /var/lib/apt/lists/*

# Cache de deps independiente del código
COPY requirements.txt pyproject.toml* ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt

COPY . .

# Tests opcionales durante el build (puedes moverlos al workflow si ralentiza mucho)
# RUN /opt/venv/bin/pytest -q tests/

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim-bookworm AS runtime

RUN adduser --system --group --no-create-home app \
 && apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar solo el venv y el código (no build deps)
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build /app

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT={{PORT}}

USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:${PORT}{{HEALTH_PATH}} || exit 1

EXPOSE {{PORT}}

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "{{PROJECT_NAME}}"]
