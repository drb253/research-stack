#!/usr/bin/env python3
"""openserp_unwrap.py -- resolve the wrapped result links of OpenSERP.

Google answers the OpenSERP browser profile with one encrypted redirect per organic
result:  https://www.google.com/goto?url=CAES...  .  Every such result therefore
carries url=google.com/goto?..., domain=google.com and display_url="google.com > goto",
which makes the record unusable for a citation or for domain reasoning.  That is
upstream issue #53; the attribution fix (commit 98e48e6) is in no release yet.

The link is not a dead end.  One plain GET returns HTTP 302 with the real address in
the Location header.  This tool follows that single hop and rewrites url, domain,
display_url and domain_info, keeping the original in wrapped_url.

A link that does not resolve keeps its original URL and gains "unwrapped": false.
An unresolved wrapper is never presented as a real address.

Exit codes (the repository's convention):
  0  every wrapper resolved, or no wrapper present
  1  at least one wrapper failed to resolve
  2  input gap: the input is not JSON, or it carries no result list       (never a pass)
  4  input gap: a required argument is missing                              (never a pass)

Usage:
  curl -s 'http://127.0.0.1:7000/google/search?text=x&limit=5' | openserp_unwrap.py
  openserp_unwrap.py --url 'https://www.google.com/goto?url=CAES...'
  openserp_unwrap.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")
TIMEOUT = 12
WRAPPER_MARKERS = ("/goto?url=", "/url?q=")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop at the first 3xx so its Location header can be read."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def is_wrapped(url: str) -> bool:
    return bool(url) and any(marker in url for marker in WRAPPER_MARKERS)


def resolve(url: str):
    """Return the real address behind a wrapped link, or None."""
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            location = response.headers.get("Location")
            if not location and response.status in (200, 204):
                return None          # a page arrived instead of a redirect
            return location
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location") if exc.headers else None
        return location
    except Exception:
        return None


def registrable(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    if "@" in host:
        host = host.split("@", 1)[1]
    if host.startswith("www."):
        host = host[4:]
    return host.split(":", 1)[0]


def unwrap_item(item: dict) -> bool:
    """Rewrite one result record in place.  Return True when it is usable."""
    original = item.get("url") or ""
    if not is_wrapped(original):
        return True
    real = resolve(original)
    if not real or not real.startswith("http"):
        item["unwrapped"] = False
        return False
    if is_wrapped(real):
        item["unwrapped"] = False   # a second wrapper: stop, do not guess
        return False
    host = registrable(real)
    parsed = urllib.parse.urlparse(real)
    path = parsed.path.strip("/")
    item["url"] = real
    item["wrapped_url"] = original
    item["domain"] = host
    item["display_url"] = "%s \u203a %s" % (host, path) if path else host
    tail = host.split(".")[-1] if "." in host else ""
    item["domain_info"] = {"tld": tail,
                           "sld": host[: -len(tail) - 1] if tail else host,
                           "category": ""}
    item["unwrapped"] = True
    return True


def unwrap_records(records, workers: int = 4):
    todo = [r for r in records if isinstance(r, dict) and is_wrapped(r.get("url"))]
    if not todo:
        return 0, 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(unwrap_item, todo))
    return len(todo), results.count(False)


# --- main -------------------------------------------------------------------- #
def main(argv=None, stream=None) -> int:
    parser = argparse.ArgumentParser(description="Resolve wrapped OpenSERP result links.")
    parser.add_argument("--url", action="append", default=[], help="resolve this link (repeatable)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    if args.url:
        status = 0
        for link in args.url:
            real = resolve(link)
            if real:
                print(real)
            else:
                print("UNRESOLVED\t%s" % link, file=sys.stderr)
                status = 1
        return status

    text = stream.read() if stream is not None else sys.stdin.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print("openserp_unwrap: the input is not JSON (%s)" % exc, file=sys.stderr)
        return 2
    records = data.get("results") if isinstance(data, dict) else data
    if not isinstance(records, list):
        print("openserp_unwrap: no result list found", file=sys.stderr)
        return 2

    total, failed = unwrap_records(records, args.workers)
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    if total:
        print("openserp_unwrap: %d/%d wrapped links resolved" % (total - failed, total),
              file=sys.stderr)
    return 1 if failed else 0


# --- offline self-test ------------------------------------------------------- #
class _Stub(BaseHTTPRequestHandler):
    """A local stand-in for a wrapped link: one redirect, one dead end."""

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        value = (query.get("url") or [""])[0]
        if parsed.path == "/goto" and value == "ok":
            self.send_response(302)
            self.send_header("Location", "https://example.org/paper")
            self.end_headers()
            return
        if parsed.path == "/goto" and value == "double":
            self.send_response(302)
            self.send_header("Location", "/goto?url=ok")
            self.end_headers()
            return
        body = b"<html><body>no redirect here</body></html>"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


def _run(argv, stdin_text=None) -> int:
    """Call main() with the output captured, so the report stays clean."""
    import contextlib
    import io
    stream = io.StringIO(stdin_text if stdin_text is not None else "")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return main(argv, stream=stream)


def self_test() -> int:
    passed = failed = 0

    def check(name, got, want):
        nonlocal passed, failed
        if got == want:
            passed += 1
            print("  PASS %s" % name)
        else:
            failed += 1
            print("  FAIL %s (want %r, got %r)" % (name, want, got))

    server = HTTPServer(("127.0.0.1", 0), _Stub)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % port
    try:
        ok = {"url": "%s/goto?url=ok" % base, "domain": "google.com"}
        check("a redirect resolves", unwrap_item(ok), True)
        check("the address is rewritten", ok.get("url"), "https://example.org/paper")
        check("the domain is rewritten", ok.get("domain"), "example.org")
        check("the original address is kept", ok.get("wrapped_url"), "%s/goto?url=ok" % base)
        check("the success is labelled", ok.get("unwrapped"), True)
        check("the display url is rebuilt", ok.get("display_url"), "example.org \u203a paper")

        dead = {"url": "%s/goto?url=fail" % base, "domain": "google.com"}
        check("a page without a redirect fails", unwrap_item(dead), False)
        check("the failure keeps the address", dead.get("url"), "%s/goto?url=fail" % base)
        check("the failure is labelled", dead.get("unwrapped"), False)

        twice = {"url": "%s/goto?url=double" % base}
        check("a second wrapper is refused", unwrap_item(twice), False)

        check("a plain address is not wrapped", is_wrapped("https://example.org/x"), False)
        check("a goto address is wrapped", is_wrapped("https://www.google.com/goto?url=x"), True)
        check("a url?q address is wrapped", is_wrapped("https://x.test/url?q=y"), True)
        check("www is stripped", registrable("https://www.example.org/a"), "example.org")
        check("a port is stripped", registrable("http://example.org:8080/a"), "example.org")

        check("a good link exits 0", _run(["--url", "%s/goto?url=ok" % base]), 0)
        check("a dead link exits 1", _run(["--url", "%s/goto?url=fail" % base]), 1)
        check("text input exits 2", _run([], "not json at all"), 2)
        check("an error body exits 2", _run([], '{"error": "blocked"}'), 2)
        clean = {"results": [{"url": "https://example.org/x", "domain": "example.org"}]}
        check("a clean payload exits 0", _run([], json.dumps(clean)), 0)
        mixed = {"results": [{"url": "%s/goto?url=ok" % base},
                             {"url": "%s/goto?url=fail" % base}]}
        check("one dead link in a list exits 1", _run([], json.dumps(mixed)), 1)
    finally:
        server.shutdown()
        server.server_close()

    print("openserp_unwrap: %d passed, %d failed" % (passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
