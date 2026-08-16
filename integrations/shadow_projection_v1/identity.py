import hashlib
import json
from typing import Any
from urllib.parse import quote

DEFAULT_NAMESPACE = "https://id.example.invalid"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def stable_uri(kind: str, stable_key: str, namespace: str = DEFAULT_NAMESPACE) -> str:
    if not kind or not stable_key:
        raise ValueError("kind and stable_key are required")
    return "%s/%s/%s" % (
        namespace.rstrip("/"),
        quote(kind, safe=""),
        quote(stable_key, safe=""),
    )


def evidence_uri_from_digest(
    content_digest: str, namespace: str = DEFAULT_NAMESPACE
) -> str:
    if not content_digest:
        raise ValueError("content_digest is required")
    return "%s/evidence/sha256/%s" % (
        namespace.rstrip("/"),
        quote(content_digest, safe=""),
    )
