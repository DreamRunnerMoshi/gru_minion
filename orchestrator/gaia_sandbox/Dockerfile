# exp6 GAIA sandbox: a plain, network-enabled container (unlike SWE-bench's per-instance
# images, which check out a repo and get no internet). No repo to check out here — just a
# Python environment with common research/parsing packages and the web_search helper both
# Gru and the minion invoke.
FROM python:3.11-slim

RUN pip install --no-cache-dir \
    requests \
    beautifulsoup4 \
    lxml \
    pandas \
    numpy \
    sympy

COPY websearch.py /usr/local/bin/websearch.py
RUN chmod +x /usr/local/bin/websearch.py

WORKDIR /workspace
