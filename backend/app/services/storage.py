"""S3 / MinIO object storage service."""

from __future__ import annotations

import io
from typing import BinaryIO, Iterator, Optional
from uuid import UUID

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageService:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.public_url = settings.s3_public_url.rstrip("/")
        endpoint = settings.s3_endpoint_url.rstrip("/")
        client_kwargs = dict(
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )
        # Internal client for upload/download inside Docker (minio:9000).
        self.client = boto3.client("s3", endpoint_url=endpoint, **client_kwargs)
        # Sign browser URLs with the public host so SigV4 Host matches the request.
        # generate_presigned_url is local crypto — no network call to public_url needed.
        if self.public_url and self.public_url != endpoint:
            self.presign_client = boto3.client(
                "s3", endpoint_url=self.public_url, **client_kwargs
            )
        else:
            self.presign_client = self.client
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self.client.create_bucket(Bucket=self.bucket)
                # Public-read policy for MVP downloads via public URL
                policy = (
                    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":"*",'
                    '"Action":["s3:GetObject"],"Resource":["arn:aws:s3:::%s/*"]}]}'
                    % self.bucket
                )
                try:
                    self.client.put_bucket_policy(Bucket=self.bucket, Policy=policy)
                except ClientError as exc:
                    logger.warning("Could not set bucket policy: %s", exc)
                logger.info("Created storage bucket %s", self.bucket)
            except ClientError as exc:
                logger.error("Failed to create bucket: %s", exc)
                raise

    @staticmethod
    def project_key(project_id: UUID | str, category: str, filename: str) -> str:
        return f"projects/{project_id}/{category}/{filename}"

    def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    def upload_fileobj(
        self,
        key: str,
        fileobj: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> str:
        self.client.upload_fileobj(
            fileobj,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return key

    def upload_file(self, key: str, path: str, content_type: str = "application/octet-stream") -> str:
        self.client.upload_file(
            path,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        return key

    def download_bytes(self, key: str) -> bytes:
        buf = io.BytesIO()
        self.client.download_fileobj(self.bucket, key, buf)
        return buf.getvalue()

    def download_file(self, key: str, path: str) -> str:
        self.client.download_file(self.bucket, key, path)
        return path

    def iter_object(self, key: str, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        """Stream an object in chunks via the internal S3 client (no browser cookies)."""
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body = response["Body"]
        try:
            while True:
                chunk = body.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            logger.warning("Failed to delete %s: %s", key, exc)

    def public_url_for(self, key: str) -> str:
        return f"{self.public_url}/{self.bucket}/{key}"

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return self.presign_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )


_storage: Optional[StorageService] = None


def get_storage() -> StorageService:
    global _storage
    if _storage is None:
        _storage = StorageService()
    return _storage
