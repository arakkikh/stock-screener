"""個人情報（資金・保有・売買記録・損益）がリポジトリに入らないことの確認。

これらはブラウザの localStorage にだけ保存する決まり。公開データ（docs/data）や画面のコードに、
保存・送信の経路ができていないかを機械的に調べる。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERSONAL_KEYS = ("positions", "settings:money", "buyPrice", "stop0", "riskPct", "violations")


def test_public_data_has_no_personal_records():
    for path in (ROOT / "docs" / "data").rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        for key in PERSONAL_KEYS:
            assert f'"{key}"' not in text, f"{path.relative_to(ROOT)} に個人の記録らしき項目 {key} があります"


def test_no_exported_backup_is_committed():
    # 画面の「エクスポート」で作ったファイル（stock-screener-日付.json）がリポジトリに入っていない
    for path in ROOT.rglob("*.json"):
        if ".venv" in path.parts or "node_modules" in path.parts:
            continue
        if path.name.startswith("stock-screener-"):
            raise AssertionError(f"エクスポートしたファイルがあります: {path.relative_to(ROOT)}")
        if path.stat().st_size < 2_000_000:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            assert not (isinstance(data, dict) and data.get("app") == "stock-screener"), path


def test_screen_code_never_sends_data_out():
    # 画面のコードは JSON を読む（GET）だけで、外へ送る手段を使っていない
    forbidden = re.compile(r"sendBeacon|XMLHttpRequest|WebSocket|method\s*:\s*[\"'](POST|PUT|PATCH)")
    for path in (ROOT / "docs" / "js").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), f"{path.name} に外へ送る処理があります"
        for call in re.findall(r"fetch\(([^)]*)\)", text):
            assert "localStorage" not in call and "store" not in call, f"{path.name}: {call}"


def test_python_never_touches_browser_storage_keys():
    for path in list((ROOT / "scripts").glob("*.py")) + list((ROOT / "screener").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "settings:money" not in text and "screener:positions" not in text, path
