"""
S3-compatible object storage abstraction (spec Section 5/94). Only this module ever talks to a
storage backend - services/routes never construct a storage client directly (docs/architecture.md
component boundary). MinIO/boto3 aren't installed in this sandbox (no network), so this ships
with a local-disk implementation as the default for now; swapping in a real S3/MinIO client is a
new class implementing the same interface, not a change to any caller.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Protocol


class ObjectStorage(Protocol):
    async def put(self, organisation_id: int, file_bytes: bytes, extension: str) -> str:
        """Returns the storage_key - never the original filename (spec Section 94: 'never trust
        filenames')."""
        ...

    async def get(self, storage_key: str) -> bytes: ...


class LocalDiskStorage:
    """Stand-in implementation for local development / this sandbox. NOT for production - no
    encryption at rest, no access control beyond filesystem permissions. Swap for an S3/MinIO
    implementation before deploying anywhere real."""

    def __init__(self, base_path: str = "/tmp/procureiq-uploads") -> None:
        self.base_path = Path(base_path)

    async def put(self, organisation_id: int, file_bytes: bytes, extension: str) -> str:
        key = f"{organisation_id}/{uuid.uuid4()}.{extension.lstrip('.')}"
        target = self.base_path / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_bytes)
        return key

    async def get(self, storage_key: str) -> bytes:
        return (self.base_path / storage_key).read_bytes()


_default_storage = LocalDiskStorage()


def get_storage() -> ObjectStorage:
    return _default_storage
