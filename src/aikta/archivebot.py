import asyncio
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

import aiohttp

VIEWER_URL = "https://archive.fart.website/archivebot/viewer"
JOBS_URL = f"{VIEWER_URL}/jobs"

_HOST_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-.")


def extract_domain(arg: str) -> str:
    """Return the lowercase hostname (without port) for a URL or bare domain.

    Accepts any scheme, with optional userinfo/port/path/query. Returns ""
    for anything that does not look like a plausible hostname (never raises).
    """
    if not arg or not arg.strip():
        return ""
    text = arg.strip()
    if "://" not in text:
        text = "//" + text  # bare domain, possibly with port/path/query
    host = urlsplit(text).hostname or ""
    if "." not in host or not set(host) <= _HOST_CHARS:
        return ""
    for label in host.split("."):
        if not label or label.startswith("-") or label.endswith("-"):
            return ""
    return host


class _TableRowParser(HTMLParser):
    """Collect the cells of every <tr> as (text, hrefs) pairs.

    Keeps only text inside <td>/<th> cells, with the href targets of any
    <a> collected alongside. Unexpected markup degrades to extra or empty
    cells instead of raising.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self._in_table = False
        self._in_row = False
        self._cell_tag = None
        self._cell_text = []
        self._cell_hrefs = []
        self._cells = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._cells = []
        elif self._in_row and tag in ("td", "th"):
            self._cell_tag = tag
            self._cell_text = []
            self._cell_hrefs = []
        elif self._cell_tag and tag == "a":
            href = dict(attrs).get("href")
            if href is not None:
                self._cell_hrefs.append(href)

    def handle_data(self, data):
        if self._cell_tag is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell_tag == tag:
            self._cells.append(("".join(self._cell_text).strip(), self._cell_hrefs))
            self._cell_tag = None
        elif tag == "tr" and self._in_row:
            self.rows.append(self._cells)
            self._in_row = False
        elif tag == "table":
            self._in_table = False
            self._in_row = False
            self._cell_tag = None


def _is_job_id(value: str) -> bool:
    """ArchiveBot job ids are 14-digit UTC timestamps, e.g. 20131013224154."""
    return len(value) == 14 and value.isascii() and value.isdigit()


def _job_id_from_cell(text: str, hrefs: list) -> str:
    for href in hrefs:
        candidate = href.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        if _is_job_id(candidate):
            return candidate
    return text if _is_job_id(text) else ""


def _parse_index(html: str) -> list[dict]:
    """Extract {id, domain, url} rows from the viewer jobs table.

    The header row and malformed rows (wrong cell count, non-timestamp id)
    are skipped without raising.
    """
    parser = _TableRowParser()
    parser.feed(html)
    rows = []
    for cells in parser.rows:
        if len(cells) != 3:
            continue
        (id_text, id_hrefs), (domain, _), (url, _) = cells
        job_id = _job_id_from_cell(id_text, id_hrefs)
        if not job_id or not domain or not url:
            continue
        rows.append({"id": job_id, "domain": domain.lower(), "url": url})
    return rows


def _shallow_from_filename(name: str) -> bool | None:
    """Read the shallow flag out of an ArchiveBot artifact name.

    Artifacts are named <domain>-inf|shallow-YYYYMMDD-HHMMSS.json; True for
    "shallow", False for "inf", None when the name is not an artifact name.
    """
    stem = name.strip()
    if stem.endswith(".json"):
        stem = stem[: -len(".json")]
    parts = stem.split("-")
    if len(parts) < 3:
        return None
    kind, date, clock = parts[-3], parts[-2], parts[-1]
    if kind not in ("inf", "shallow"):
        return None
    stamp = date + clock
    if len(date) != 8 or len(clock) != 6:
        return None
    if not stamp.isascii() or not stamp.isdigit():
        return None
    return kind == "shallow"


def _parse_detail_shallow(html: str) -> bool | None:
    """Scan a job detail page for the first artifact name with a shallow flag."""
    parser = _TableRowParser()
    parser.feed(html)
    for cells in parser.rows:
        for text, _hrefs in cells:
            flag = _shallow_from_filename(text)
            if flag is not None:
                return flag
    return None


def _format_job_time(job_id: str) -> str:
    """Format a job id timestamp as UTC, e.g. 20131013224154
    -> 2013-10-13 22:41:54 UTC."""
    dt = datetime.strptime(job_id, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


class ArchiveBot:
    """Client for the ArchiveBot viewer index at archive.fart.website.

    Transport-agnostic: methods return reply strings; the caller sends them.
    The ~1000-row jobs index is cached with a TTL (default 600s); the
    shallow flag of a job is read from its detail page once and cached per
    job id (unknown flags are not cached, so a failed detail fetch retries).
    """

    def __init__(self, ttl: int = 600):
        self.ttl = ttl
        self.session = aiohttp.ClientSession()
        self._index_lock = asyncio.Lock()
        self._index_rows = None
        self._index_time = 0.0
        self._shallow_flags = {}

    async def close(self):
        await self.session.close()

    async def get_domain_report(self, domain: str) -> str:
        """Full reply line for a `!ab <link|domain>` query.

        `<domain>: last job <UTC ts> (<job-id>), shallow: yes/no, subdomains:
        <N archived>` with up to 3 example subdomains then "+N more";
        `<domain>: not in the viewer index (~1000-row cap)` on zero matches;
        `<arg>: not a domain I can use` for unparseable args; and
        `<domain>: viewer unreachable` / `shallow: ?` on fetch failures.
        """
        arg = domain.strip()
        host = extract_domain(arg)
        if not host:
            return f"{arg}: not a domain I can use"
        try:
            rows = await self._get_index_rows()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return f"{host}: viewer unreachable"
        matches = [
            row for row in rows
            if row["domain"] == host or row["domain"].endswith("." + host)
        ]
        if not matches:
            return f"{host}: not in the viewer index (~1000-row cap)"
        last = max(matches, key=lambda row: row["id"])
        shallow = await self._get_shallow(last["id"])
        shallow_text = {True: "yes", False: "no", None: "?"}[shallow]
        subdomains = {}
        for row in matches:
            if row["domain"] != host:
                seen = subdomains.get(row["domain"], "")
                subdomains[row["domain"]] = max(seen, row["id"])
        recent = sorted(subdomains, key=subdomains.get, reverse=True)
        if recent:
            head = ", ".join(recent[:3])
            more = f", +{len(recent) - 3} more" if len(recent) > 3 else ""
            sub_text = f"subdomains: {len(recent)} archived: {head}{more}"
        else:
            sub_text = "subdomains: 0 archived"
        return (
            f"{host}: last job {_format_job_time(last['id'])} ({last['id']}), "
            f"shallow: {shallow_text}, {sub_text}"
        )

    async def _get_index_rows(self) -> list[dict]:
        now = time.monotonic()
        if self._index_rows is not None and now - self._index_time < self.ttl:
            return self._index_rows
        async with self._index_lock:
            now = time.monotonic()
            if self._index_rows is not None and now - self._index_time < self.ttl:
                return self._index_rows
            html = await self._fetch(JOBS_URL)
            rows = _parse_index(html)
            self._index_rows = rows
            self._index_time = time.monotonic()
            return rows

    async def _get_shallow(self, job_id: str) -> bool | None:
        if job_id in self._shallow_flags:
            return self._shallow_flags[job_id]
        try:
            html = await self._fetch(f"{VIEWER_URL}/job/{job_id}")
            flag = _parse_detail_shallow(html)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
            return None
        if flag is not None:
            self._shallow_flags[job_id] = flag
        return flag

    async def _fetch(self, url: str) -> str:
        async with self.session.get(url) as response:
            response.raise_for_status()
            return await response.text()
