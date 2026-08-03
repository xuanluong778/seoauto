"""Object storage adapter — Cloudflare R2 / S3 compatible (default) + local fallback.

Plugin ZIPs are never stored in the database or source tree; only storage_key metadata.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Iterator
from urllib.parse import urlparse


class StorageAdapter(ABC):
    """Minimal object-storage interface for private plugin packages."""

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/zip") -> str:
        """Upload object; return storage key."""

    @abstractmethod
    def put_file(self, key: str, path: str | Path, *, content_type: str = "application/zip") -> str:
        """Upload local file; return storage key."""

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        """Download entire object."""

    @abstractmethod
    def open_stream(self, key: str) -> Iterator[bytes]:
        """Yield object body in chunks."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        ...

    def presign_get(self, key: str, expires_in: int = 900) -> str | None:
        """Optional short-lived GET URL. Default: not used (app proxies download)."""
        return None


class LocalStorageAdapter(StorageAdapter):
    """Filesystem fallback for staging / offline."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(
            root
            or os.getenv(
                "WP_PLUGIN_RELEASE_STORAGE",
                str(Path(__file__).resolve().parents[2] / "data" / "plugin_releases"),
            )
        )
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        key = key.lstrip("/").replace("\\", "/")
        if ".." in key.split("/"):
            raise ValueError("invalid storage key")
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError("path escape")
        return path

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/zip") -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def put_file(self, key: str, path: str | Path, *, content_type: str = "application/zip") -> str:
        return self.put_bytes(key, Path(path).read_bytes(), content_type=content_type)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def open_stream(self, key: str) -> Iterator[bytes]:
        with self._path(key).open("rb") as fh:
            while True:
                chunk = fh.read(1024 * 256)
                if not chunk:
                    break
                yield chunk

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()


class S3StorageAdapter(StorageAdapter):
    """Cloudflare R2 or any S3-compatible endpoint (boto3)."""

    def __init__(
        self,
        *,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        prefix: str | None = None,
    ) -> None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("boto3 is required for R2/S3 storage (pip install boto3)") from exc

        self.bucket = (bucket or os.getenv("R2_BUCKET") or os.getenv("S3_BUCKET") or "").strip()
        if not self.bucket:
            raise RuntimeError("R2_BUCKET / S3_BUCKET is required for S3StorageAdapter")
        self.prefix = (prefix or os.getenv("R2_PREFIX") or os.getenv("S3_PREFIX") or "plugin-releases").strip().strip("/")
        endpoint = (
            endpoint_url
            or os.getenv("R2_ENDPOINT_URL")
            or os.getenv("S3_ENDPOINT_URL")
            or ""
        ).strip() or None
        region = (region or os.getenv("R2_REGION") or os.getenv("AWS_REGION") or "auto").strip()
        ak = (access_key or os.getenv("R2_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID") or "").strip()
        sk = (secret_key or os.getenv("R2_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY") or "").strip()
        force_path = (os.getenv("R2_FORCE_PATH_STYLE") or os.getenv("S3_FORCE_PATH_STYLE") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        s3_config: dict = {"addressing_style": "path"} if force_path else {}

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=ak or None,
            aws_secret_access_key=sk or None,
            config=Config(signature_version="s3v4", s3=s3_config),
        )

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        if self.prefix and not key.startswith(self.prefix + "/") and key != self.prefix:
            return f"{self.prefix}/{key}"
        return key

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/zip") -> str:
        full = self._full_key(key)
        self._client.put_object(Bucket=self.bucket, Key=full, Body=data, ContentType=content_type)
        return key

    def put_file(self, key: str, path: str | Path, *, content_type: str = "application/zip") -> str:
        full = self._full_key(key)
        self._client.upload_file(
            str(path),
            self.bucket,
            full,
            ExtraArgs={"ContentType": content_type},
        )
        return key

    def get_bytes(self, key: str) -> bytes:
        full = self._full_key(key)
        obj = self._client.get_object(Bucket=self.bucket, Key=full)
        return obj["Body"].read()

    def open_stream(self, key: str) -> Iterator[bytes]:
        full = self._full_key(key)
        obj = self._client.get_object(Bucket=self.bucket, Key=full)
        body = obj["Body"]
        while True:
            chunk = body.read(1024 * 256)
            if not chunk:
                break
            yield chunk

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        full = self._full_key(key)
        try:
            self._client.head_object(Bucket=self.bucket, Key=full)
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        full = self._full_key(key)
        self._client.delete_object(Bucket=self.bucket, Key=full)

    def presign_get(self, key: str, expires_in: int = 900) -> str | None:
        full = self._full_key(key)
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": full},
            ExpiresIn=max(60, int(expires_in)),
        )


def get_storage_adapter() -> StorageAdapter:
    """Factory: R2/S3 when configured, else local disk."""
    backend = (os.getenv("WP_PLUGIN_STORAGE_BACKEND") or "").strip().lower()
    if not backend:
        if (os.getenv("R2_BUCKET") or os.getenv("S3_BUCKET") or "").strip():
            backend = "r2"
        else:
            backend = "local"
    if backend in {"r2", "s3", "s3compat"}:
        return S3StorageAdapter()
    return LocalStorageAdapter()


def build_release_storage_key(*, slug: str, channel: str, version: str, filename: str | None = None) -> str:
    """Canonical object key — never embeds secrets."""
    name = filename or f"{slug}-{version}.zip"
    return f"{slug}/{channel}/{version}/{name}"


def looks_like_storage_key(value: str) -> bool:
    v = (value or "").strip()
    if not v or v.startswith("/") or "://" in v:
        # Absolute paths / URLs are legacy local paths, not object keys.
        if "://" in v:
            return False
        # Windows absolute path
        if len(v) > 2 and v[1] == ":":
            return False
        if v.startswith("/"):
            return False
    return "/" in v and ".." not in v


def redact_url_for_log(url: str) -> str:
    """Never log full signed download URLs."""
    try:
        p = urlparse(url)
        host = p.netloc or "?"
        path = (p.path or "")[:48]
        return f"{p.scheme}://{host}{path}…"
    except Exception:
        return "[redacted-url]"
