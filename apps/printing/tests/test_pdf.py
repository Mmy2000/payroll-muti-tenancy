"""The PDF renderer (headless Chromium): it makes PDFs, and it loads nothing but our own static
and media files, with no scripts."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from apps.printing import pdf


@pytest.fixture(scope="module")
def chromium():
    try:
        pdf.html_to_pdf("<p>ok</p>")
    except pdf.PdfUnavailable:
        pytest.skip("Chromium is not installed (python -m playwright install chromium)")


def test_html_becomes_a_pdf(chromium):
    assert pdf.html_to_pdf("<p dir='rtl'>كشف المرتبات</p>").startswith(b"%PDF-")


def test_local_files_only():
    content, kind = pdf._local_file("/static/core/fonts/plex-arabic-400.woff2")
    assert content and kind == "font/woff2"
    assert pdf._local_file("/static/core/fonts/nope.woff2") is None
    assert pdf._local_file("/media/../config/settings/base.py") is None
    assert pdf._local_file("/etc/passwd") is None


def test_the_renderer_fetches_nothing_and_runs_no_scripts(chromium):
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        html = (f'<img src="{base}/img.png"><link rel="stylesheet" href="{base}/x.css">'
                f'<script>fetch("{base}/script"); document.write("ran")</script>'
                f'<iframe src="{base}/frame"></iframe>')
        assert pdf.html_to_pdf(html).startswith(b"%PDF-")
    finally:
        server.shutdown()
    assert hits == []
