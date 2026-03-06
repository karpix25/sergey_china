import os
import logging

logger = logging.getLogger(__name__)

def cleanup_local_files(*file_paths):
    """Safely delete local files if they exist."""
    for path in file_paths:
        if path and isinstance(path, str) and os.path.exists(path):
            try:
                os.remove(path)
                logger.info("  - Deleted temporary file: %s", path)
            except Exception as e:
                logger.warning("  - Failed to delete %s: %s", path, e)
