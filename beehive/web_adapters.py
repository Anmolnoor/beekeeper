from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


def _domain_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return (parsed.hostname or "").lower()


def _strip_html(text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", text)
    compact = re.sub(r"\s+", " ", no_tags).strip()
    return compact


@dataclass
class WebAdapterError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass
class SearxngAdapter:
    base_url: str = "http://localhost:8080"
    timeout_seconds: int = 20

    def _request_json(self, url: str) -> dict[str, Any]:
        req = urllib.request.Request(url=url, method="GET", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict):
                return payload
            raise WebAdapterError("provider_error", "searxng returned non-object payload")
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise WebAdapterError("rate_limit", "searxng rate limited request") from exc
            raise WebAdapterError("provider_error", f"searxng http_error={exc.code}") from exc
        except urllib.error.URLError as exc:
            raise WebAdapterError("unavailable", f"searxng unavailable: {exc}") from exc
        except TimeoutError as exc:
            raise WebAdapterError("timeout", "searxng request timed out") from exc

    def search(self, query: str, allowed_domains: list[str], limit: int = 5) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        q = query.strip()
        if allowed_domains:
            domain_filter = " OR ".join(f"site:{domain}" for domain in allowed_domains)
            q = f"{q} {domain_filter}"
        params = urllib.parse.urlencode(
            {
                "q": q,
                "format": "json",
                "language": "en",
                "safesearch": "1",
            }
        )
        payload = self._request_json(f"{self.base_url.rstrip('/')}/search?{params}")
        rows = payload.get("results", [])
        if not isinstance(rows, list):
            raise WebAdapterError("provider_error", "searxng results field invalid")
        cleaned: list[dict[str, Any]] = []
        allowed = {item.lower() for item in allowed_domains}
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url", "")).strip()
            if not url:
                continue
            domain = _domain_from_url(url)
            if allowed and domain not in allowed:
                continue
            cleaned.append(
                {
                    "title": str(row.get("title", "untitled")).strip() or "untitled",
                    "url": url,
                    "domain": domain,
                    "snippet": str(row.get("content", "")).strip(),
                    "source": "searxng",
                }
            )
            if len(cleaned) >= max(1, limit):
                break
        return cleaned

    def fetch(self, url: str) -> str:
        req = urllib.request.Request(
            url=url,
            method="GET",
            headers={"User-Agent": "beehive-agent/0.1", "Accept": "text/html,application/xhtml+xml"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
                content_type = str(response.headers.get("Content-Type", "")).lower()
                body = response.read().decode("utf-8", errors="ignore")
            if "html" in content_type:
                return _strip_html(body)[:2000]
            return body[:2000]
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise WebAdapterError("rate_limit", "fetch rate limited") from exc
            raise WebAdapterError("provider_error", f"fetch http_error={exc.code}") from exc
        except urllib.error.URLError as exc:
            raise WebAdapterError("unavailable", f"fetch unavailable: {exc}") from exc
        except TimeoutError as exc:
            raise WebAdapterError("timeout", "fetch timed out") from exc
