"""R5 远端证书透明度（CT）校验客户端。

本地 CT 是 append-only hash chain；远端 CT 提供可验证回执：
Ed25519 签名 + Merkle inclusion proof（RFC 6962 风格的 leaf/node hash 前缀）。
不做公网日志写入的默认自动提交；anchor 需要显式调用。

安全约定：
- 验签公钥必须来自 catalog（可信来源），绝不采用回执自带的 public_key；
- 如果回执自带 public_key，必须与可信公钥一致，否则拒绝；
- leaf 只覆盖"条目本身"，签名覆盖"条目 + root + proof"，防止证明被掉包。
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# Merkle 结构与签名元字段不参与 leaf 内容；签名覆盖除 signature/public_key 之外的全部字段。
CT_STRUCTURAL_FIELDS = frozenset({"signature", "public_key", "proof", "root"})


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def entry_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    """回执中被 Merkle leaf 承诺的条目内容。"""
    return {key: value for key, value in receipt.items()
            if key not in CT_STRUCTURAL_FIELDS}


def signed_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    """被 Ed25519 签名的完整声明（含 root/proof，但不含签名与公钥）。"""
    return {key: value for key, value in receipt.items()
            if key not in ("signature", "public_key")}


def leaf_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(b"\x00" + canonical(payload).encode("utf-8")).hexdigest()


def node_hash(left: str, right: str) -> str:
    return hashlib.sha256(b"\x01" + bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def verify_inclusion(receipt: dict[str, Any]) -> bool:
    payload = entry_payload(receipt)
    if not payload:
        return False
    proof = receipt.get("proof") or []
    root = str(receipt.get("root", "")).strip().lower()
    if not isinstance(proof, list) or not _is_sha256(root):
        return False
    current = leaf_hash(payload)
    for item in proof:
        if not isinstance(item, dict):
            return False
        sibling = str(item.get("hash", "")).strip().lower()
        direction = str(item.get("direction", "")).strip().lower()
        if not _is_sha256(sibling):
            return False
        if direction == "left":
            current = node_hash(sibling, current)
        elif direction == "right":
            current = node_hash(current, sibling)
        else:
            return False
    return current == root


def verify_ed25519(data: bytes, signature_b64: str, public_key_pem: str) -> None:
    openssl = shutil.which("openssl")
    if not openssl:
        raise RuntimeError("CT 回执验签需要 openssl")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("CT signature 不是合法 base64") from exc
    key_text = str(public_key_pem).strip()
    if not key_text:
        raise ValueError("缺少 CT 公钥")
    with tempfile.TemporaryDirectory(prefix="yoai-ct-verify-") as tmp:
        data_path = Path(tmp) / "data.bin"
        sig_path = Path(tmp) / "data.sig"
        key_path = Path(tmp) / "public.pem"
        data_path.write_bytes(data)
        sig_path.write_bytes(signature)
        key_path.write_text(key_text + "\n", encoding="utf-8")
        try:
            completed = subprocess.run(
                [openssl, "pkeyutl", "-verify", "-pubin", "-inkey", str(key_path),
                 "-rawin", "-in", str(data_path), "-sigfile", str(sig_path)],
                capture_output=True, text=True, timeout=30, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"CT 验签失败：{exc}") from exc
    if completed.returncode != 0:
        raise ValueError(f"CT 回执签名无效：{(completed.stderr or '').strip()[:300]}")


class RemoteCtClient:
    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    @staticmethod
    def http_url(value: str) -> bool:
        return str(value).strip().lower().startswith(("http://", "https://"))

    def _get(self, url: str) -> bytes:
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                return response.read()
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"CT 查询失败：{url}（{exc}）") from exc

    def fetch(self, ct_url: str, sha256: str) -> dict[str, Any]:
        if not self.http_url(ct_url):
            raise ValueError("CT 地址必须是 http/https")
        url = ct_url.rstrip("/") + "/" + urllib.parse.quote(sha256)
        try:
            data = json.loads(self._get(url).decode("utf-8"))
        except ValueError as exc:
            raise ValueError("CT 回执不是合法 JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("CT 回执格式错误")
        return data

    def anchor(self, ct_url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """显式把条目提交到远端 CT；是否接受锚定回执仍由 verify 决定。"""
        if not self.http_url(ct_url):
            raise ValueError("CT 地址必须是 http/https")
        request = urllib.request.Request(
            ct_url.rstrip("/") + "/anchor",
            data=canonical(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"CT 锚定失败：{exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("CT 锚定回执格式错误")
        return data

    def verify(self, receipt: dict[str, Any], public_key_pem: str) -> bool:
        key = str(public_key_pem).strip()
        if not key:
            raise ValueError("catalog 未配置 ct_public_key，无法验证 CT 回执")
        embedded = str(receipt.get("public_key", "")).strip()
        if embedded and embedded != key:
            raise ValueError("CT 回执自带公钥与可信公钥不一致")
        signature = str(receipt.get("signature", "")).strip()
        if not signature:
            return False
        verify_ed25519(canonical(signed_payload(receipt)).encode("utf-8"),
                       signature, key)
        return verify_inclusion(receipt)
