# Phantom on-prem updater service.
#
# Minimal sidecar that drives the host's docker daemon via the mounted
# /var/run/docker.sock. Ships its own image so it can keep running while
# phantom-agent (and the others) are being replaced during an update.
#
# Image surface:
#   - Python 3.12 + uvicorn + FastAPI app on :8090
#   - docker CLI + compose plugin (so we can subprocess `docker compose
#     up -d <service>` against the host install dir)
#
# We deliberately do NOT install the docker daemon — this container
# drives the HOST's daemon. The CLI alone is sufficient.

# Base pinned by digest. Update via:
#   docker pull python:3.12-slim && \
#     docker inspect --format='{{index .RepoDigests 0}}' python:3.12-slim
# Pinning keeps the phantom-updater image content-addressed across
# source-unchanged rebuilds. See CLAUDE.md § Per-service path-filter
# contract.
FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461 AS runtime

# Install docker CLI + compose plugin from Docker's apt repo. Pinned
# to the codename of the base (debian bookworm at time of writing).
# Curl + gnupg are removed at the end of the layer to slim the image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && . /etc/os-release \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        docker-ce-cli docker-compose-plugin \
    && apt-get purge -y --auto-remove gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer-cache pip install separately from source.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

EXPOSE 8090

# uvicorn directly — no extra process supervisor needed. Docker is
# our PID-1 (compose's restart policy handles crashes).
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8090"]
