"""Polite HTTP.

Every outbound request goes through here so three things are guaranteed:

  * robots.txt is honoured. A disallowed path is not fetched, full stop.
  * requests to the same host are spaced out.
  * the User-Agent says what this is, so an admin who sees it in a log can
    tell what hit them and block it if they want to.

Bot protections are never evaded. A 403, a 429 or a CAPTCHA is treated as the
site saying no, and the source is skipped.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field

USER_AGENT = (
    "job_applier/0.2 (personal job-search tool; "
    "contact via the operator of this machine)"
)

DEFAULT_MIN_INTERVAL = 1.5   # seconds between requests to one host
DEFAULT_TIMEOUT = 30


class Blocked(RuntimeError):
    """The site declined the request. Not retried, not worked around."""


class RobotsDisallowed(Blocked):
    """robots.txt forbids this path."""


class NotFound(RuntimeError):
    """There is nothing at this URL. Distinct from Blocked: a company that
    does not run a board on this platform is a normal answer, not a refusal."""


@dataclass
class PoliteFetcher:
    min_interval: float = DEFAULT_MIN_INTERVAL
    timeout: int = DEFAULT_TIMEOUT
    obey_robots: bool = True
    _last_hit: dict[str, float] = field(default_factory=dict)
    _robots: dict[str, urllib.robotparser.RobotFileParser | None] = field(default_factory=dict)

    # ---------- politeness ----------
    def _wait(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            gap = time.monotonic() - last
            if gap < self.min_interval:
                time.sleep(self.min_interval - gap)
        self._last_hit[host] = time.monotonic()

    def _robots_for(self, scheme: str, host: str):
        if host in self._robots:
            return self._robots[host]
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{scheme}://{host}/robots.txt")
        try:
            rp.read()
        except Exception:
            # No reachable robots.txt means no stated restriction.
            rp = None
        self._robots[host] = rp
        return rp

    def allowed(self, url: str) -> bool:
        if not self.obey_robots:
            return True
        parts = urllib.parse.urlsplit(url)
        rp = self._robots_for(parts.scheme or "https", parts.netloc)
        if rp is None:
            return True
        try:
            return rp.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    def crawl_delay(self, url: str) -> float | None:
        parts = urllib.parse.urlsplit(url)
        rp = self._robots_for(parts.scheme or "https", parts.netloc)
        if rp is None:
            return None
        try:
            d = rp.crawl_delay(USER_AGENT)
            return float(d) if d else None
        except Exception:
            return None

    # ---------- requests ----------
    def get(self, url: str, headers: dict[str, str] | None = None) -> bytes:
        if not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")

        host = urllib.parse.urlsplit(url).netloc
        delay = self.crawl_delay(url)
        if delay and delay > self.min_interval:
            self._last_hit[host] = self._last_hit.get(host, 0.0)
            time.sleep(delay)
        self._wait(host)

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/html;q=0.8, */*;q=0.5",
                "Accept-Language": "en-SG,en;q=0.9",
                **(headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise NotFound(f"nothing at {url}") from e
            if e.code in (401, 403, 429, 451):
                raise Blocked(
                    f"{host} returned HTTP {e.code} — treating that as a refusal "
                    "and skipping this source"
                ) from e
            raise
        except urllib.error.URLError as e:
            raise Blocked(f"could not reach {host}: {e.reason}") from e

    def get_json(self, url: str, headers: dict[str, str] | None = None):
        raw = self.get(url, headers)
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as e:
            raise Blocked(f"{url} did not return JSON (got {len(raw)} bytes)") from e


# A single shared fetcher keeps the rate limiting global across sources.
fetcher = PoliteFetcher()
