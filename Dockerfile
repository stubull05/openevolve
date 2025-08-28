# Use an official Python runtime as the base image
FROM python:3.13-slim AS base

# Ensure system packages are up to date
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip, setuptools, and wheel globally at build time
RUN python3 -m pip install --no-cache-dir -U pip setuptools wheel

# Set working directory
WORKDIR /workspace

# Copy requirements first (to leverage Docker cache)
COPY requirements.txt /workspace/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire repo
COPY . /workspace

# Make entrypoint executable
RUN chmod +x /usr/local/bin/entrypoint.sh || true

# Environment variables (override with .env via docker-compose)
ENV OE_REPO_DIR=/workspace/target \
    OE_TARGET_FILE=api.py \
    OE_RUN_MODE=evolve

# Run entrypoint
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
