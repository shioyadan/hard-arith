FROM mcr.microsoft.com/devcontainers/base:noble

RUN apt-get update \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libgmp-dev \
        libmpfr-dev \
        python3 \
        python3-mpmath \
        verilator=5.020-1 \
    && rm -rf /var/lib/apt/lists/*
