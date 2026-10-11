FROM python:3.12-slim

WORKDIR /app

# Copy dependency files
COPY requirements.txt ./

# Upgrade pip and install build dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and resources
COPY src/ ./src/
COPY resources/ ./resources/

# Copy default skills to a staging location
# These will be copied to /app/skills on first run if volume is empty
COPY skills/ ./skills-default/

# Create empty skills directory for volume mount
RUN mkdir -p /app/skills

# v1.2 stage 3A — `data_root` for instance-store sqlite + future
# per-agent state. Mounted as a named volume by docker-compose so it
# survives container restarts.
RUN mkdir -p /app/data

# Copy and set up entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV MCP_TRANSPORT=stdio
# Connector tool source lives in the bundle (mounted at /app/bundle
# by docker-compose). PYTHONPATH includes /app/src for MCP imports
# (`from config.config`, `from pkg.X`) and /app/bundle for connectors.
ENV PYTHONPATH=/app:/app/src:/app/bundle

# Run the entrypoint script
ENTRYPOINT ["/app/entrypoint.sh"]
