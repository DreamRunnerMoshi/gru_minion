# Available tools in this sandbox

- **Web search**: `python3 /usr/local/bin/websearch.py "<query>"` — prints JSON results
  (title, url, snippet) for a real web search. Prefer this over writing your own
  `curl`/`urllib`/`requests` scraper against a search engine directly — those get
  blocked or return unparseable HTML; this tool exists specifically so you don't have
  to build that yourself.
- **Python**: `python3 -c "<code>"` — `requests`, `beautifulsoup4`, `lxml`, `pandas`,
  `numpy`, `sympy` are installed, for calculation, parsing, or fetching a specific
  known URL directly.
