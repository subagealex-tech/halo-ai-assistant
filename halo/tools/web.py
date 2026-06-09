import logging
from typing import Any, ClassVar

import httpx

from halo.tools.base import BaseTool

log = logging.getLogger("halo.tools.web")

SEARCH_URL = "https://api.duckduckgo.com/?q={query}&format=json&no_html=1"


class WebSearchTool(BaseTool):
    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = "Search the web for current information. Returns a list of relevant results."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query string",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (1-10)",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def execute(self, query: str, max_results: int = 5, **kwargs: Any) -> Any:
        try:
            resp = httpx.get(
                f"https://html.duckduckgo.com/html/?q={query}",
                follow_redirects=True,
                timeout=15.0,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; HALO/1.0)",
                },
            )
            return {
                "status": "ok",
                "source": "duckduckgo",
                "query": query,
                "snippet": resp.text[:3000],
            }
        except Exception as e:
            log.warning("Web search failed: %s", e)
            return {"status": "error", "error": str(e)}


class WebFetchTool(BaseTool):
    name: ClassVar[str] = "web_fetch"
    description: ClassVar[str] = "Fetch the content of a URL and return it as markdown or text."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return",
                "default": 5000,
            },
        },
        "required": ["url"],
    }

    def execute(self, url: str, max_chars: int = 5000, **kwargs: Any) -> Any:
        try:
            resp = httpx.get(url, follow_redirects=True, timeout=30.0)
            resp.raise_for_status()
            content = resp.text[:max_chars]
            return {
                "status": "ok",
                "url": url,
                "content": content,
                "content_type": resp.headers.get("content-type", ""),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}
