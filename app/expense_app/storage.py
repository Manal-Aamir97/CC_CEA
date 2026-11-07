"""Receipt storage on Amazon S3 (cloud-native enhancement).

The EC2 instance role grants Put/Get/Delete on s3://<bucket>/receipts/* only.
No access keys are used: boto3 picks up temporary role credentials from the
instance metadata service automatically. Objects stay private; viewers get a
short-lived pre-signed URL.
"""
import uuid
from datetime import date

from flask import current_app

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "pdf"}


def enabled() -> bool:
    return bool(current_app.config.get("S3_BUCKET"))


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _client():
    import boto3  # imported lazily so tests run without AWS

    return boto3.client("s3", region_name=current_app.config["AWS_REGION"])


def upload_receipt(file_storage, user_id: int) -> str:
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    key = f"receipts/{user_id}/{date.today():%Y/%m}/{uuid.uuid4().hex}.{ext}"
    _client().upload_fileobj(
        file_storage.stream,
        current_app.config["S3_BUCKET"],
        key,
        ExtraArgs={
            "ContentType": file_storage.mimetype or "application/octet-stream",
            "ServerSideEncryption": "AES256",
        },
    )
    return key


def presigned_url(key: str, expires: int = 300) -> str:
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": current_app.config["S3_BUCKET"], "Key": key},
        ExpiresIn=expires,
    )


def delete_receipt(key: str) -> None:
    _client().delete_object(Bucket=current_app.config["S3_BUCKET"], Key=key)
