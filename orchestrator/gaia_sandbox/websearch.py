#!/usr/bin/env python3
"""Web search helper for the GAIA sandbox image — wraps the Tavily API.

Used two ways: Gru's own `web_search` tool calls this directly (via GaiaEnvironment,
same container as everything else); a minion in agentic mode invokes it as a plain
bash command (`python3 /usr/local/bin/websearch.py "<query>"`), same as any other
tool it has access to — no separate implementation needed for the two callers.

Needs TAVILY_API_KEY in the environment (forwarded into the container — see
orchestrator/config/gaia-session.yaml's forward_env).
"""

import json
import os
import sys

import requests

TAVILY_URL = "https://api.tavily.com/search"


def search(query: str, max_results: int = 5) -> dict:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {"error": "TAVILY_API_KEY not set in the sandbox environment"}
    resp = requests.post(
        TAVILY_URL,
        json={
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "query": query,
        "results": [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in data.get("results", [])
        ],
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: websearch.py <query>"}))
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    try:
        result = search(query)
    except Exception as e:
        result = {"error": f"{type(e).__name__}: {e}"}
    print(json.dumps(result, indent=2))
