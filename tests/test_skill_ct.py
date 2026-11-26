"""R5 远端证书透明度回执测试：Merkle proof、Ed25519、安装拦截与锚定。"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from yoai.skills import RemoteCtClient, SkillMarket, SkillStore
from yoai.skills.ct import canonical, leaf_hash, node_hash, verify_inclusion


@pytest.fixture(scope="module")
def ct_key(tmp_path_factory) -> tuple[Path, str]:
    if not shutil.which("openssl"):
        pytest.skip("openssl not available")
    root = tmp_path_factory.mktemp("ct-key")
    private = root / "ct.pem"
    public = root / "ct_pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
                   check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
                   check=True, capture_output=True)
    return private, public.read_text(encoding="utf-8")


def _sign(private: Path, data: bytes) -> str:
    with tempfile.TemporaryDirectory(prefix="yoai-ct-sign-") as tmp:
        path = Path(tmp) / "payload.bin"
        path.write_bytes(data)
        signed = subprocess.run(
            ["openssl", "pkeyutl", "-sign", "-inkey", str(private),
             "-rawin", "-in", str(path)],
            check=True, capture_output=True).stdout
    return base64.b64encode(signed).decode("ascii")


def _signed_statement(receipt: dict[str, Any]) -> bytes:
    return canonical({k: v for k, v in receipt.items()
                      if k not in ("signature", "public_key")}).encode("utf-8")


def _receipt(entry: dict[str, Any], private: Path, *,
             sibling: str = "ab" * 32, tamper_proof: bool = False,
             embed_key: str = "") -> dict[str, Any]:
    proof_hash = "cd" * 32 if tamper_proof else sibling
    proof = [{"direction": "right", "hash": proof_hash}]
    root = node_hash(leaf_hash(entry), sibling)
    receipt = {**entry, "proof": proof, "root": root}
    if embed_key:
        receipt["public_key"] = embed_key
    receipt["signature"] = _sign(private, _signed_statement(receipt))
    return receipt


def _zip(name: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("skill.json", json.dumps({
            "name": name, "prompt": "p", "tools": [], "requirements": [],
        }, ensure_ascii=False))
    return buf.getvalue()


def _skip_deps(monkeypatch) -> None:
    monkeypatch.setattr(
        SkillMarket, "install_dependencies",
        lambda self, name: {"ok": False, "reason": "test skip", "log": ""})


def test_ct_receipt_signature_and_inclusion(ct_key, tmp_path):
    private, public = ct_key
    entry = {"sha256": hashlib.sha256(b"pkg").hexdigest(), "name": "demo"}
    receipt = _receipt(entry, private)
    client = RemoteCtClient()

    assert verify_inclusion(receipt) is True
    assert client.verify(receipt, public) is True

    tampered = dict(receipt)
    tampered["proof"] = [{"direction": "right", "hash": "ef" * 32}]
    tampered["signature"] = _sign(private, _signed_statement(tampered))
    assert verify_inclusion(tampered) is False
    assert client.verify(tampered, public) is False

    changed = {**receipt, "sha256": "0" * 64}
    with pytest.raises(ValueError, match="签名无效"):
        client.verify(changed, public)

    with pytest.raises(ValueError, match="ct_public_key"):
        client.verify(receipt, "")

    other_private = tmp_path / "other.pem"
    other_public = tmp_path / "other_pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519",
                    "-out", str(other_private)], check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(other_private), "-pubout",
                    "-out", str(other_public)], check=True, capture_output=True)
    embedded = dict(receipt)
    embedded["public_key"] = other_public.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="自带公钥"):
        client.verify(embedded, public)


def _serve_ct_market(monkeypatch, tmp_path, ct_key, *,
                     tamper_receipt: bool = False,
                     include_ct_key: bool = True,
                     ) -> tuple[str, str, bytes, dict[str, Any],
                                ThreadingHTTPServer, threading.Thread]:
    _skip_deps(monkeypatch)
    private, public = ct_key
    name = "ct-demo"
    package = _zip(name)
    digest = hashlib.sha256(package).hexdigest()
    state: dict[str, Any] = {"base": "", "catalog": {}, "receipts": {}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def _send(self, body: bytes, ctype: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            base = state["base"]
            if self.path == "/catalog.json":
                self._send(json.dumps(state["catalog"], ensure_ascii=False).encode("utf-8"),
                           "application/json")
            elif self.path == "/pkg.zip":
                self._send(package, "application/zip")
            elif self.path.startswith("/ct/"):
                sha = self.path.rsplit("/", 1)[-1]
                receipt = state["receipts"].get(sha)
                if receipt is None:
                    self.send_error(404)
                    return
                self._send(json.dumps(receipt, ensure_ascii=False).encode("utf-8"),
                           "application/json")
            else:
                self.send_error(404)

        def do_POST(self):  # noqa: N802
            if self.path not in ("/anchor", "/ct/anchor"):
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            entry = json.loads(self.rfile.read(length).decode("utf-8"))
            receipt = _receipt(entry, private)
            state["receipts"][str(entry.get("sha256", ""))] = receipt
            self._send(json.dumps(receipt, ensure_ascii=False).encode("utf-8"),
                       "application/json")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    state["base"] = base
    catalog_entry: dict[str, Any] = {
        "name": name, "version": "1.0", "description": "CT 演示",
        "url": f"{base}/pkg.zip", "sha256": digest,
        "ct_url": f"{base}/ct",
    }
    if include_ct_key:
        catalog_entry["ct_public_key"] = public
    state["catalog"] = {"skills": [catalog_entry]}
    state["receipts"][digest] = _receipt(
        {"sha256": digest, "name": name, "catalog_url": f"{base}/catalog.json"},
        private, tamper_proof=tamper_receipt)
    return base, name, package, state, server, thread


def test_remote_install_ct_verify_and_anchor(monkeypatch, tmp_path, ct_key):
    base, name, _package, _state, server, thread = _serve_ct_market(
        monkeypatch, tmp_path, ct_key)
    try:
        store = SkillStore(tmp_path)
        market = SkillMarket(tmp_path, store)
        market.add_remote(f"{base}/catalog.json")
        result = market.install(name)
        assert result["package_sha256"] == hashlib.sha256(_package).hexdigest()

        item = next(i for i in market.list() if i["name"] == name)
        assert item["ct_url"] == f"{base}/ct"
        assert item["ct_receipt_hash"]

        verified = market.ct_verify(name)
        assert verified["ok"] is True
        assert verified["action"] == "verify"
        assert verified["sha256"] == result["package_sha256"]

        before = market.verify_ct()[1]
        anchored = market.ct_anchor(name)
        assert anchored["ok"] is True, anchored["reason"]
        assert anchored["action"] == "anchor"
        assert market.verify_ct()[1] == before + 1
        assert market.status()["transparency"]["valid"] is True
        assert market.ct_verify(name)["ok"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_remote_install_rejects_tampered_ct(monkeypatch, tmp_path, ct_key):
    base, name, _package, _state, server, thread = _serve_ct_market(
        monkeypatch, tmp_path, ct_key, tamper_receipt=True)
    try:
        store = SkillStore(tmp_path)
        market = SkillMarket(tmp_path, store)
        market.add_remote(f"{base}/catalog.json")
        with pytest.raises(ValueError, match="CT 回执"):
            market.install(name)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_remote_install_rejects_ct_without_trusted_key(monkeypatch, tmp_path, ct_key):
    base, name, _package, _state, server, thread = _serve_ct_market(
        monkeypatch, tmp_path, ct_key, include_ct_key=False)
    try:
        store = SkillStore(tmp_path)
        market = SkillMarket(tmp_path, store)
        market.add_remote(f"{base}/catalog.json")
        with pytest.raises(ValueError, match="ct_public_key"):
            market.install(name)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
