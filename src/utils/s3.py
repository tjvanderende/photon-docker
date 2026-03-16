import os
import sys
import time
from urllib.parse import urlparse

from src.utils import config
from src.utils.logger import get_logger

logging = get_logger()


def is_s3_url(url: str) -> bool:
    return url.startswith("s3://")


def parse_s3_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def get_s3_client():
    import boto3

    endpoint_url = os.getenv("AWS_ENDPOINT_URL") or os.getenv("S3_ENDPOINT_URL")
    return boto3.client("s3", **({"endpoint_url": endpoint_url} if endpoint_url else {}))


def get_s3_file_size(url: str) -> int:
    bucket, key = parse_s3_url(url)
    s3 = get_s3_client()
    response = s3.head_object(Bucket=bucket, Key=key)
    return response["ContentLength"]


def download_s3_file(url: str, destination: str) -> bool:
    from tqdm import tqdm

    bucket, key = parse_s3_url(url)
    s3 = get_s3_client()

    start_time = time.time()
    max_retries = int(config.DOWNLOAD_MAX_RETRIES)

    for attempt in range(max_retries):
        try:
            head = s3.head_object(Bucket=bucket, Key=key)
            total_size = head["ContentLength"]

            logging.info(f"Starting S3 download: s3://{bucket}/{key} ({total_size / (1024**3):.2f}GB)")

            progress_bar = None
            if total_size > 0:
                try:
                    progress_bar = tqdm(
                        desc=f"Downloading {os.path.basename(destination)}",
                        total=total_size,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                        leave=True,
                        disable=None,
                        file=sys.stderr,
                    )
                except Exception:
                    pass

            def progress_callback(bytes_transferred):
                if progress_bar:
                    progress_bar.update(bytes_transferred)

            try:
                s3.download_file(bucket, key, destination, Callback=progress_callback)
            finally:
                if progress_bar:
                    progress_bar.close()

            duration = time.time() - start_time
            if total_size > 0:
                speed_mbps = (total_size * 8) / (duration * 1_000_000)
                duration_minutes = duration / 60
                logging.info(
                    f"S3 download completed: {total_size / (1024**3):.2f}GB in {duration:.1f}s ({duration_minutes:.1f}m) at {speed_mbps:.1f} Mbps"
                )
            else:
                logging.info(f"Downloaded {destination} successfully from S3.")

            return True

        except Exception as e:
            logging.warning(f"S3 download attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                wait_time = 2**attempt
                logging.info(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
                logging.info(f"Retrying S3 download (attempt {attempt + 2}/{max_retries})...")
                continue
            logging.exception(f"S3 download failed after {max_retries} attempts")
            return False

    return False
