"""Skill 本地市场守护测试：登记、安装、发布、移除。"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from yoai.skills import SkillMarket, SkillStore


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "source-pkg"
    package.mkdir(parents=True, exist_ok=True)
    (package / "skill.json").write_text(json.dumps({
        "name": "demo", "description": "演示", "prompt": "提示词",
        "tools": ["web_search"], "requirements": ["requests==2.31.0"],
        "scripts": [], "resources": [],
    }, ensure_ascii=False), encoding="utf-8")
    return package


def test_market_add_install_publish_remove(tmp_path):
    store = SkillStore(tmp_path)
    market = SkillMarket(tmp_path, store)
    package = _package(tmp_path)

    entry = market.add_local(package)
    assert entry["name"] == "demo"
    assert market.list()[0]["source"] == str(package.resolve())

    installed = market.install("demo")
    assert Path(installed["target"]).is_dir()
    assert (tmp_path / "skills" / "demo" / "requirements.txt").exists()
    assert any(s["name"] == "demo" for s in store.status()["skills"])
    assert market.list()[0]["installed"] is True

    published = market.publish("demo")
    assert Path(published["source"]).is_dir()
    assert (Path(published["source"]) / "skill.json").exists()
    assert any(i["name"] == "demo" for i in market.list())

    assert market.remove("demo") is True
    assert market.list() == []


def test_remote_market_install(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skill.json", json.dumps({
            "name": "remote-demo", "description": "远端演示", "prompt": "提示",
            "tools": [], "requirements": ["requests==2.31.0"],
        }, ensure_ascii=False))
        zf.writestr("requirements.txt", "requests==2.31.0\n")
    package = buf.getvalue()
    catalog = {"skills": [{
        "name": "remote-demo", "version": "1.0.0", "description": "远端演示",
        "url": "/pkg.zip", "sha256": hashlib.sha256(package).hexdigest(),
        "requirements": ["requests==2.31.0"],
        "lockfile": "requests==2.31.0\n",
    }]}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):  # noqa: N802
            if self.path == "/catalog.json":
                body = json.dumps(catalog, ensure_ascii=False).encode("utf-8")
                ctype = "application/json"
            elif self.path == "/pkg.zip":
                body, ctype = package, "application/zip"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        store = SkillStore(tmp_path)
        market = SkillMarket(tmp_path, store)
        market.add_remote(f"{base}/catalog.json")
        item = next(i for i in market.list() if i["name"] == "remote-demo")
        assert item["source_type"] == "remote"

        result = market.install("remote-demo")
        installed = Path(result["target"])
        assert (installed / "skill.json").exists()
        assert "requests" in (installed / "requirements.txt").read_text(encoding="utf-8")
        assert (installed / "requirements.lock.txt").exists()
    finally:
        server.shutdown()
        thread.join(timeout=3)
