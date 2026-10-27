"""Object storage abstraction with encryption at rest.

Binary medical data (images, X-rays, audio, annotated images) is never stored in relational tables.
Every object is encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before it reaches disk or S3.
"""
import logging
import os
from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger("dentedge.storage")


class StorageBackend(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    def healthy(self) -> bool:
        return True


def _safe_key(key: str) -> str:
    parts = [p for p in key.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts:
        raise ValueError("Invalid storage key")
    return "/".join(parts)


class LocalStorage(StorageBackend):
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / _safe_key(key)).resolve()
        if self.root not in path.parents:
            raise ValueError("Storage key escapes storage root")
        return path

    def put(self, key, data):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def get(self, key):
        return self._path(key).read_bytes()

    def delete(self, key):
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            pass

    def healthy(self):
        return os.access(self.root, os.W_OK)


class S3Storage(StorageBackend):  # pragma: no cover - requires cloud credentials
    def __init__(self):
        import boto3  # optional dependency
        kwargs = {"region_name": settings.s3_region or None}
        if settings.s3_endpoint_url:
            kwargs["endpoint_url"] = settings.s3_endpoint_url
        self.client = boto3.client("s3", **kwargs)
        self.bucket = settings.s3_bucket

    def _k(self, key):
        return f"{settings.s3_prefix}/{_safe_key(key)}"

    def put(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=self._k(key), Body=data, ServerSideEncryption="AES256")

    def get(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=self._k(key))["Body"].read()

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=self._k(key))

    def healthy(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


def _load_key() -> bytes:
    if settings.storage_encryption_key:
        return settings.storage_encryption_key.encode()
    # Non-production convenience: persist a generated key next to the dev upload volume.
    key_file = Path(settings.upload_dir).resolve() / ".dev_storage_key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        return key_file.read_bytes().strip()
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    logger.warning("STORAGE_ENCRYPTION_KEY not set; generated a development key at %s", key_file)
    return key


class EncryptedStorage:
    def __init__(self, backend: StorageBackend, key: bytes):
        self.backend = backend
        self.fernet = Fernet(key)

    def put(self, key: str, data: bytes) -> None:
        self.backend.put(key, self.fernet.encrypt(data))

    def get(self, key: str) -> bytes:
        raw = self.backend.get(key)
        try:
            return self.fernet.decrypt(raw)
        except InvalidToken:
            raise ValueError("Stored object could not be decrypted (wrong key or tampered file)")

    def delete(self, key: str) -> None:
        self.backend.delete(key)

    def healthy(self) -> bool:
        return self.backend.healthy()


@lru_cache
def get_storage() -> EncryptedStorage:
    backend: StorageBackend = S3Storage() if settings.storage_backend == "s3" else LocalStorage(settings.upload_dir)
    return EncryptedStorage(backend, _load_key())
