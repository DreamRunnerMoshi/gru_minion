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

# Discoverability, not documentation: this is the actual mechanism, not a nicety. Caught
# live (exp6, gemini-3.7-flash) — a model that doesn't know websearch.py exists spends its
# whole turn budget reinventing scraping via raw urllib against Google/DuckDuckGo/YouTube/
# archive.org, none of which reliably work, and never recovers. Sitting a plain-named file
# in cwd means a routine `ls` (something both models tested here did as an early step, GLM's
# minion within its first handful of turns) surfaces it for free — no prompt change needed,
# same fix applies to any future model pointed at this sandbox regardless of what's in its
# system prompt.
COPY TOOLS.md /workspace/TOOLS.md
