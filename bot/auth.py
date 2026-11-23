"""Ed25519 authentication for Revolut X API."""

import base64
import json
import time
from pathlib import Path
from urllib.parse import urlencode

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)


def generate_keypair(private_path: str = "private.pem", public_path: str = "public.pem") -> str:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    Path(private_path).write_bytes(private_pem)
    Path(private_path).chmod(0o600)
    Path(public_path).write_bytes(public_pem)

    return public_pem.decode()


def load_private_key(path: str) -> Ed25519PrivateKey:
    pem_data = Path(path).read_bytes()
    key = load_pem_private_key(pem_data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"Expected Ed25519 key, got {type(key).__name__}")
    return key


def sign_request(
    private_key: Ed25519PrivateKey,
    method: str,
    path: str,
    query_params: dict | None = None,
    body: dict | None = None,
    timestamp_ms: int | None = None,
) -> tuple[str, str]:
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    ts_str = str(timestamp_ms)

    parts = [ts_str, method.upper(), path]

    if query_params:
        qs = urlencode(sorted(query_params.items()))
        parts.append(qs)
    else:
        parts.append("")

    if body:
        parts.append(json.dumps(body, separators=(",", ":")))
    else:
        parts.append("")

    message = "\n".join(parts)
    signature = private_key.sign(message.encode())
    sig_b64 = base64.b64encode(signature).decode()

    return ts_str, sig_b64
