"""Idempotently create the configured S3 bucket, retrying while storage starts up."""

import asyncio
import logging
import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.storage import get_storage

logger = logging.getLogger("ensure_bucket")

_ATTEMPTS = 30
_DELAY_S = 2.0


async def main() -> int:
    configure_logging(get_settings().log_level)
    storage = get_storage()
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            created = await storage.ensure_bucket()
        except Exception as exc:
            logger.warning(
                "storage not ready", extra={"attempt": attempt, "error": type(exc).__name__}
            )
            await asyncio.sleep(_DELAY_S)
            continue
        logger.info("bucket ready", extra={"bucket": storage.bucket, "bucket_created": created})
        return 0
    logger.error("giving up creating bucket", extra={"bucket": storage.bucket})
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
