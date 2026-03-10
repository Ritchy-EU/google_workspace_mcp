"""
Drive write restriction decorator.

Restricts write operations to a configurable list of allowed shared drive IDs.
When ALLOWED_WRITE_DRIVE_IDS is set, only writes to those drives are permitted.
When empty/unset, no restrictions apply.
"""

import logging
from functools import wraps

from core.config import ALLOWED_WRITE_DRIVE_IDS
from gdrive.drive_helpers import get_file_drive_id

logger = logging.getLogger(__name__)


def restrict_to_drives(target_param: str):
    """
    Decorator that restricts write operations to allowed shared drives.

    Must be placed BELOW @require_google_service so that the `service`
    parameter is available.

    Args:
        target_param: Name of the function parameter containing the
                      target file/folder ID to check (e.g. "file_id", "folder_id").
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not ALLOWED_WRITE_DRIVE_IDS:
                return await func(*args, **kwargs)

            # service is always the first positional arg (injected by @require_google_service)
            service = args[0] if args else kwargs.get("service")
            target_id = kwargs.get(target_param)

            # Also check positional args if not in kwargs
            if target_id is None and args:
                import inspect

                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if target_param in params:
                    idx = params.index(target_param)
                    if idx < len(args):
                        target_id = args[idx]

            if target_id is None or target_id == "root":
                raise ValueError(
                    f"Write access denied: target is in My Drive, not in an allowed shared drive. "
                    f"Allowed drive IDs: {ALLOWED_WRITE_DRIVE_IDS}"
                )

            drive_id = await get_file_drive_id(service, target_id)

            if drive_id is None:
                raise ValueError(
                    f"Write access denied: target '{target_id}' is in My Drive, "
                    f"not in an allowed shared drive. "
                    f"Allowed drive IDs: {ALLOWED_WRITE_DRIVE_IDS}"
                )

            if drive_id not in ALLOWED_WRITE_DRIVE_IDS:
                raise ValueError(
                    f"Write access denied: target '{target_id}' belongs to drive '{drive_id}' "
                    f"which is not in the allowed list. "
                    f"Allowed drive IDs: {ALLOWED_WRITE_DRIVE_IDS}"
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
