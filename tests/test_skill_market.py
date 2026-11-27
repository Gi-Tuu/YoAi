"""Skill 本地市场守护测试：登记、安装、发布、移除。"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

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


def _skip_deps(monkeypatch):
    monkeypatch.setattr(SkillMarket, "install_dependencies",
                        lambda self, name: {"ok": False, "reason": "test skip", "log": ""})


def test_market_add_install_publish_remove(tmp_path, monkeypatch):
    _skip_deps(monkeypatch)
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
    assert installed["rsi_node_id"]
    from yoai.evolution import EvolutionArchive
    archive = EvolutionArchive(tmp_path / "evolution" / "evolution.json")
    assert archive.get(installed["rsi_node_id"]).lifecycle == "candidate"

    published = market.publish("demo")
    assert Path(published["source"]).is_dir()
    assert (Path(published["source"]) / "skill.json").exists()
    assert any(i["name"] == "demo" for i in market.list())

    assert market.remove("demo") is True
    assert market.list() == []


def test_remote_market_install(tmp_path, monkeypatch):
    _skip_deps(monkeypatch)
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


def test_install_dependencies_uses_lock_and_venv(tmp_path, monkeypatch):
    store = SkillStore(tmp_path)
    market = SkillMarket(tmp_path, store)
    installed = tmp_path / "skills" / "demo"
    installed.mkdir(parents=True, exist_ok=True)
    (installed / "requirements.lock.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    calls = []
    def fake_run(command, **_kwargs):
        calls.append(command)
        if "-m" in command and "venv" in command:
            venv_py = SkillMarket._venv_python(installed / ".venv")
            venv_py.parent.mkdir(parents=True, exist_ok=True)
            venv_py.write_bytes(b"")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = market.install_dependencies("demo")
    assert result["ok"] is True and result["installed"] is True
    assert any("requirements.lock.txt" in str(c) for c in calls)
    assert (installed / "deps_install.log").exists()


def _sign_with_key(key: Path, data: bytes) -> bytes:
    path = tmp = None
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "data.bin"
        path.write_bytes(data)
        return subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(path)],
            check=True, capture_output=True).stdout


def test_remote_signature_chain_and_transparency(tmp_path, monkeypatch):
    _skip_deps(monkeypatch)
    if not shutil.which("openssl"):
        pytest.skip("openssl not available")
    root = tmp_path / "root.pem"
    signer = tmp_path / "signer.pem"
    root_pub = tmp_path / "root_pub.pem"
    signer_pub = tmp_path / "signer_pub.pem"
    for key in (root, signer):
        subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
                       check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(root), "-pubout", "-out", str(root_pub)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(signer), "-pubout", "-out", str(signer_pub)],
                   check=True, capture_output=True)

    signer_text = signer_pub.read_text(encoding="utf-8")
    cert_sig = base64.b64encode(_sign_with_key(root, signer_text.encode("utf-8"))).decode("ascii")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skill.json", json.dumps({
            "name": "chain-demo", "prompt": "p", "tools": [],
        }, ensure_ascii=False))
    package = buf.getvalue()
    package_sig = base64.b64encode(_sign_with_key(signer, package)).decode("ascii")
    catalog = {"skills": [{
        "name": "chain-demo", "version": "1.0", "url": "/pkg.zip",
        "root_public_key": root_pub.read_text(encoding="utf-8"),
        "signer_public_key": signer_text,
        "signer_cert_signature": cert_sig,
        "signature": package_sig,
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
        market.install("chain-demo")
        ok, count = market.verify_ct()
        assert ok and count == 1
        assert market.status()["transparency"]["valid"] is True
    finally:
        server.shutdown()
        thread.join(timeout=3)


def test_remote_signature_verification(tmp_path, monkeypatch):
    _skip_deps(monkeypatch)
    if not shutil_which("openssl"):
        pytest.skip("openssl not available")
    key = tmp_path / "key.pem"
    pub = tmp_path / "pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(key)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(pub)],
                   check=True, capture_output=True)
    payload = b"signed-package"
    payload_path = tmp_path / "payload.bin"
    payload_path.write_bytes(payload)
    signed = subprocess.run(
        ["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(payload_path)],
        check=True, capture_output=True).stdout
    public_text = pub.read_text(encoding="utf-8")
    signature = base64.b64encode(signed).decode("ascii")

    store = SkillStore(tmp_path)
    market = SkillMarket(tmp_path, store)
    market._verify_ed25519(payload, signature, public_text)
    with pytest.raises(ValueError):
        market._verify_ed25519(b"tampered", signature, public_text)


def shutil_which(name: str) -> str | None:
    return shutil.which(name)
