"""
Drive write restriction decorator.

Restricts write operations to a configurable list of allowed shared drive IDs.
When ALLOWED_WRITE_DRIVE_IDS is set, writes to unlisted *shared* drives are
blocked. Writes to My Drive are always allowed regardless of this setting.
When empty/unset, no restrictions apply at all.

Works with any Google service type (Drive, Docs, Sheets, Slides).
For non-Drive services, a temporary Drive service is built from the
existing service's credentials to perform the check.
"""

import asyncio
import inspect
import logging
from functools import wraps
from typing import Optional

from googleapiclient.discovery import build

from core.config import ALLOWED_WRITE_DRIVE_IDS

logger = logging.getLogger(__name__)


async def _get_drive_id_for_file(service, file_id: str) -> Optional[str]:
    """
    Get the shared drive ID for a file, using any Google service's credentials.

    If the service is already a Drive service (has .files()), uses it directly.
    Otherwise, extracts credentials and builds a temporary Drive service.

    Returns driveId or None (My Drive).
    """
    # Try using the service directly (works for Drive service)
    try:
        service.files()
        # If that didn't raise, this is a Drive service
        metadata = await asyncio.to_thread(
            service.files()
            .get(fileId=file_id, fields="driveId", supportsAllDrives=True)
            .execute
        )
        return metadata.get("driveId")
    except AttributeError:
        pass

    # Non-Drive service: build a temporary Drive service from credentials
    creds = service._http.credentials
    drive_service = build("drive", "v3", credentials=creds)
    try:
        metadata = await asyncio.to_thread(
            drive_service.files()
            .get(fileId=file_id, fields="driveId", supportsAllDrives=True)
            .execute
        )
        return metadata.get("driveId")
    finally:
        drive_service.close()


def restrict_to_drives(target_param: Optional[str] = None):
    """
    Decorator that restricts write operations to allowed shared drives.

    My Drive is always allowed — restrictions only apply to shared drives.
    When ALLOWED_WRITE_DRIVE_IDS is set, writes to shared drives NOT in the
    list are blocked. Writes to My Drive (root) pass through unconditionally.

    Must be placed BELOW @require_google_service so that the `service`
    parameter is available.

    Args:
        target_param: Name of the function parameter containing the
                      target file/folder ID to check (e.g. "file_id", "folder_id").
                      If None, the operation targets My Drive (e.g. create
                      operations with no folder param) and is always allowed.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not ALLOWED_WRITE_DRIVE_IDS:
                return await func(*args, **kwargs)

            # No target_param means create-in-root (My Drive) — always allowed
            if target_param is None:
                return await func(*args, **kwargs)

            # service is always the first positional arg (injected by @require_google_service)
            service = args[0] if args else kwargs.get("service")
            target_id = kwargs.get(target_param)

            # Also check positional args if not in kwargs
            if target_id is None and args:
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if target_param in params:
                    idx = params.index(target_param)
                    if idx < len(args):
                        target_id = args[idx]

            # Target is My Drive root — always allowed
            if target_id is None or target_id == "root":
                return await func(*args, **kwargs)

            # Look up which drive this file/folder belongs to
            drive_id = await _get_drive_id_for_file(service, target_id)

            # File is in My Drive (no driveId) — always allowed
            if drive_id is None:
                return await func(*args, **kwargs)

            # File is in a shared drive — check the allow-list
            if drive_id not in ALLOWED_WRITE_DRIVE_IDS:
                raise ValueError(
                    f"Write access denied: target '{target_id}' belongs to shared drive '{drive_id}' "
                    f"which is not in the allowed list. "
                    f"Allowed shared drive IDs: {ALLOWED_WRITE_DRIVE_IDS}"
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
