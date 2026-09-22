"""Offline tests for the ArchiveBot lookup module.

All HTTP is stubbed at ArchiveBot._fetch; the fixtures below mirror the
markup of https://archive.fart.website/archivebot/viewer/{jobs,job/<id>}.
Run with `python -m pytest tests/`.
"""

import asyncio

from aikta import archivebot
from aikta.archivebot import ArchiveBot, extract_domain

INDEX_HTML = """<!DOCTYPE html>
<html><head lang="en"><title> Jobs  - ArchiveBot Viewer</title></head>
<body>
    <nav>
        <a href="/archivebot/viewer/">Home</a>
        <a href="?page=2" rel="next">Next</a>
    </nav>
    <table>
        <tr>
            <th>Job Identifier</th>
            <th>Domain</th>
            <th>URL</th>
        </tr>

            <tr>
        <td><a href="/archivebot/viewer/job/20240102030405">20240102030405</a></td>
                <td>www.foo.bar</td>
                <td>http://foo.bar/</td>
            </tr>

            <tr>
        <td><a href="/archivebot/viewer/job/20231231235959">20231231235959</a></td>
                <td>foo.bar</td>
                <td>http://foo.bar/</td>
            </tr>

            <tr>
        <td><a href="/archivebot/viewer/job/20230101010101">20230101010101</a></td>
                <td>cdn.foo.bar</td>
                <td>http://cdn.foo.bar/x?a=1&amp;b=2</td>
            </tr>

            <tr>
        <td><a href="/archivebot/viewer/job/20220101010101">20220101010101</a></td>
                <td>www.foo.bar</td>
                <td>http://foo.bar/older</td>
            </tr>

            <tr>
        <td><a href="/archivebot/viewer/job/20210506070809">20210506070809</a></td>
                <td>other.org</td>
                <td>http://other.org/</td>
            </tr>

            <tr>
        <td><a href="/archivebot/viewer/job/20200101010101">20200101010101</a></td>
                <td>xfoo.bar</td>
                <td>http://xfoo.bar/</td>
            </tr>

            <tr>
        <td><a href="/archivebot/viewer/job/20191231000000">20191231000000</a></td>
                <td>truncated.example</td>
            </tr>

            <tr>
        <td><a href="/archivebot/viewer/job/notajob">notajob</a></td>
                <td>badid.example</td>
                <td>http://badid.example/</td>
            </tr>

    </table>
</body>
</html>
"""

# The viewer's job detail pages list the IA artifact file names; a job is
# shallow iff its metadata file is <domain>-shallow-<YYYYMMDD>-<HHMMSS>.json
# (regular jobs use -inf- instead).


def _detail_html(filename):
    return f"""<!DOCTYPE html>
<html><head lang="en"><title>Job - ArchiveBot Viewer</title></head>
<body>
    <h2>Job detail</h2>
    <table>
        <tr>
           <th>Filename</th>
           <th>Size</th>
           <th>IA Identifier</th>
        </tr>

            <tr>
                <td>
                    <a href="https://archive.org/download/item/{filename}">
                        {filename}
                    </a>
                </td>
                <td>147</td>
                <td>
                    <a href="/archivebot/viewer/item/some_item">
                    some_item
                    </a>
                </td>
            </tr>

    </table>
</body>
</html>
"""


DETAILS = {
    "20240102030405": _detail_html("www.foo.bar-inf-20240102-030405.json"),
    "20210506070809": _detail_html("other.org-shallow-20210506-070809.json"),
    "20200101010101": _detail_html("xfoo.bar-inf-20200101-010101.json"),
    "20230101010101": _detail_html("cdn.foo.bar-shallow-20230101-010101.json"),
}

# Six foo.bar-family rows so the "+N more" truncation path is exercised.
MORE_INDEX_HTML = """<table>
        <tr><th>Job Identifier</th><th>Domain</th><th>URL</th></tr>
        <tr><td><a href="/archivebot/viewer/job/20240101000000">20240101000000</a></td><td>foo.bar</td><td>http://foo.bar/</td></tr>
        <tr><td><a href="/archivebot/viewer/job/20240102000000">20240102000000</a></td><td>www.foo.bar</td><td>http://foo.bar/</td></tr>
        <tr><td><a href="/archivebot/viewer/job/20240103000000">20240103000000</a></td><td>cdn.foo.bar</td><td>http://cdn.foo.bar/</td></tr>
        <tr><td><a href="/archivebot/viewer/job/20240104000000">20240104000000</a></td><td>static.foo.bar</td><td>http://static.foo.bar/</td></tr>
        <tr><td><a href="/archivebot/viewer/job/20240105000000">20240105000000</a></td><td>assets.foo.bar</td><td>http://assets.foo.bar/</td></tr>
        <tr><td><a href="/archivebot/viewer/job/20240106000000">20240106000000</a></td><td>js.foo.bar</td><td>http://js.foo.bar/</td></tr>
</table>"""


class StubArchiveBot(ArchiveBot):
    """ArchiveBot with _fetch serving fixture HTML instead of the network."""

    def __init__(self, index_html=INDEX_HTML, details=None, **kwargs):
        super().__init__(**kwargs)
        self.fetches = []
        self._index_html = index_html
        self._details = DETAILS if details is None else details

    async def _fetch(self, url):
        self.fetches.append(url)
        if url == archivebot.JOBS_URL:
            return self._index_html
        job_id = url.rstrip("/").rsplit("/", 1)[-1]
        return self._details.get(job_id, "")

    def detail_fetches(self):
        return [url for url in self.fetches if url != archivebot.JOBS_URL]


def get_report(arg, **kwargs):
    async def run():
        bot = StubArchiveBot(**kwargs)
        try:
            return await bot.get_domain_report(arg)
        finally:
            await bot.close()

    return asyncio.run(run())


# --- extract_domain ---------------------------------------------------------

def test_extract_domain_from_url():
    assert extract_domain("https://foo.bar/page") == "foo.bar"


def test_extract_domain_with_port_and_query():
    assert extract_domain("http://foo.bar:8080/x?a=1") == "foo.bar"


def test_extract_domain_bare_and_uppercase():
    assert extract_domain("foo.bar") == "foo.bar"
    assert extract_domain("FOO.BAR") == "foo.bar"


def test_extract_domain_strips_irc_whitespace():
    assert extract_domain("  www.foo.bar  ") == "www.foo.bar"


def test_extract_domain_garbage_is_empty():
    assert extract_domain("!!!") == ""
    assert extract_domain("") == ""
    assert extract_domain("   ") == ""


# --- index parsing ----------------------------------------------------------

def test_parse_index_skips_header_and_malformed_rows():
    rows = archivebot._parse_index(INDEX_HTML)
    domains = [row["domain"] for row in rows]
    assert domains == [
        "www.foo.bar", "foo.bar", "cdn.foo.bar", "www.foo.bar",
        "other.org", "xfoo.bar",
    ]
    # the truncated row and the non-timestamp job id row are dropped
    assert len(rows) == 6


def test_parse_index_decodes_entities_in_url():
    rows = archivebot._parse_index(INDEX_HTML)
    assert rows[2]["url"] == "http://cdn.foo.bar/x?a=1&b=2"


def test_format_job_time():
    assert archivebot._format_job_time("20131013224154") == \
        "2013-10-13 22:41:54 UTC"


def test_shallow_flag_from_filenames():
    detect = archivebot._shallow_from_filename
    assert detect("other.org-shallow-20210506-070809.json") is True
    assert detect("darkpatterns.org-inf-20131013-224154.json") is False
    # a domain that itself contains "-shallow-" must not read as shallow
    assert detect("my-shallow-site.com-inf-20200101-010101.json") is False
    assert detect("some-random-text") is None
    assert detect("x-inf-20200101-010101.warc.gz") is None


# --- get_domain_report ------------------------------------------------------

def test_report_last_job_and_subdomains():
    assert get_report("foo.bar") == (
        "foo.bar: last job 2024-01-02 03:04:05 UTC (20240102030405), "
        "shallow: no, subdomains: 2 archived: www.foo.bar, cdn.foo.bar"
    )


def test_report_accepts_full_url():
    assert get_report("https://foo.bar/page") == get_report("foo.bar")


def test_report_shallow_yes():
    assert get_report("other.org") == (
        "other.org: last job 2021-05-06 07:08:09 UTC (20210506070809), "
        "shallow: yes, subdomains: 0 archived"
    )


def test_report_suffix_match_is_boundary_safe():
    # xfoo.bar must not match a query for foo.bar and vice versa
    assert get_report("xfoo.bar") == (
        "xfoo.bar: last job 2020-01-01 01:01:01 UTC (20200101010101), "
        "shallow: no, subdomains: 0 archived"
    )


def test_report_subdomain_query_matches_itself():
    assert get_report("cdn.foo.bar") == (
        "cdn.foo.bar: last job 2023-01-01 01:01:01 UTC (20230101010101), "
        "shallow: yes, subdomains: 0 archived"
    )


def test_report_truncates_subdomains_with_plus_more():
    assert get_report("foo.bar", index_html=MORE_INDEX_HTML, details={
        "20240106000000": _detail_html("js.foo.bar-inf-20240106-000000.json"),
    }) == (
        "foo.bar: last job 2024-01-06 00:00:00 UTC (20240106000000), "
        "shallow: no, subdomains: 5 archived: "
        "js.foo.bar, assets.foo.bar, static.foo.bar, +2 more"
    )


def test_report_zero_match():
    assert get_report("missing.example") == \
        "missing.example: not in the viewer index (~1000-row cap)"


def test_report_unparseable_arg():
    assert get_report("!!!") == "!!!: not a domain I can use"


def test_report_shallow_unknown_when_detail_missing():
    assert get_report("foo.bar", details={}) == (
        "foo.bar: last job 2024-01-02 03:04:05 UTC (20240102030405), "
        "shallow: ?, subdomains: 2 archived: www.foo.bar, cdn.foo.bar"
    )


# --- caching ----------------------------------------------------------------

def test_index_is_cached_within_ttl():
    async def run():
        bot = StubArchiveBot()
        try:
            await bot.get_domain_report("foo.bar")
            await bot.get_domain_report("other.org")
            assert bot.fetches.count(archivebot.JOBS_URL) == 1
        finally:
            await bot.close()

    asyncio.run(run())


def test_index_refetched_after_ttl_expiry():
    async def run():
        bot = StubArchiveBot(ttl=0)
        try:
            await bot.get_domain_report("foo.bar")
            await bot.get_domain_report("other.org")
            assert bot.fetches.count(archivebot.JOBS_URL) == 2
        finally:
            await bot.close()

    asyncio.run(run())


def test_shallow_flag_cached_per_job_id():
    async def run():
        bot = StubArchiveBot()
        try:
            await bot.get_domain_report("foo.bar")
            await bot.get_domain_report("www.foo.bar")  # same last job
            assert len(bot.detail_fetches()) == 1
        finally:
            await bot.close()

    asyncio.run(run())


def test_unknown_shallow_flag_is_not_cached():
    async def run():
        bot = StubArchiveBot(details={})
        try:
            await bot.get_domain_report("foo.bar")
            await bot.get_domain_report("foo.bar")
            assert len(bot.detail_fetches()) == 2
        finally:
            await bot.close()

    asyncio.run(run())
