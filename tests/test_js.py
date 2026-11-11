"""画面側（JavaScript）の計算のテストを、ブラウザを起動して実行する。"""
import functools
import http.server
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sync_api = pytest.importorskip("playwright.sync_api", reason="playwright が入っていません")


def test_javascript_logic():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    handler.log_message = lambda *args, **kwargs: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_api.sync_playwright() as p:
            try:
                browser = p.webkit.launch()
            except Exception as err:  # ブラウザ本体が未導入
                pytest.skip(f"WebKit を起動できません: {err}")
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{server.server_address[1]}/tests/js/index.html")
            page.wait_for_function("window.__results !== undefined", timeout=15000)
            results = page.evaluate("window.__results")
            browser.close()
    finally:
        server.shutdown()
    assert errors == []
    assert results["failed"] == []
    assert results["passed"] >= 36
