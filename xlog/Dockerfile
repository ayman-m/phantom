# Base image
# Pinned by digest. Update with:
#   docker pull python:3.12 && \
#     docker inspect --format='{{index .RepoDigests 0}}' python:3.12
# Pinning prevents `docker build --pull` from fetching newer upstream
# layers between source-unchanged builds, which would produce
# different image digests and force unnecessary container recreates.
FROM python:3.12@sha256:d824f747699b6a0f1ebbee9289018c1e484c808e0d928a27be5f3ed7c5f15e4b

# Set the working directory
WORKDIR /

# Copy requirements.txt
COPY requirements.txt .

# Update and install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    python3-dev \
    git \
    wget \
    swig \  
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get remove -y build-essential python3-dev git wget swig \ 
    && apt-get autoremove -y && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the application code
COPY . .

# Set the command to run the application
CMD ["python", "main.py"]
