# Agent image: repo only. Hidden tests are not in this layer.
# DeepSWE / Harbor split: agent works here; a separate verifier grades a git patch.
FROM python:3.12-slim-bookworm
RUN apt-get update \
  && apt-get install -y --no-install-recommends git \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
COPY repo/ /workspace/
RUN git config --global user.email "suite@metered.local" \
  && git config --global user.name "metered-suite" \
  && git init \
  && git add -A \
  && git commit -m base
