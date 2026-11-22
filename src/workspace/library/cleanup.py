"""Reconcile private staged files without deleting published source revisions."""
from datetime import datetime, timedelta, timezone
import logging
import re
import stat

from sqlalchemy import select

from src.workspace.library.imports import lock_storage
from src.workspace.models import Source, SourceReplacement, SourceRevision


logger = logging.getLogger(__name__)
GENERATED_KEY = re.compile(r"[0-9a-f]{32}\.(?:pdf|docx|txt|md|html)\Z")
ORPHAN_GRACE = timedelta(hours=24)


def reconcile_storage(database, root, *, now=None):
    """Remove abandoned files and old unreferenced generated files, idempotently.

    Live and historical revisions remain protected. A 24-hour grace period
    applies to unreferenced files, not explicitly abandoned attempts. No file
    is removed unless all database reference checks completed successfully.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Cleanup time must be timezone-aware.")
    cutoff = (now - ORPHAN_GRACE).timestamp()
    if not root.exists():
        return 0
    removed = 0
    with database.transaction() as session:
        lock_storage(session)
        sources = session.execute(select(Source.storage_key, Source.active_revision_id)).all()
        revisions = session.execute(select(SourceRevision.id, SourceRevision.storage_key, SourceRevision.embedding_model)).all()
        replacements = session.execute(select(SourceReplacement.storage_key, SourceReplacement.revision_id, SourceReplacement.status)).all()
        active_ids = {revision for _, revision in sources if revision is not None}
        abandoned_ids = {revision for _, revision, status in replacements if status == "abandoned" and revision is not None}
        protected = {key for key, _ in sources if key}
        protected.update(key for key, revision, status in replacements if status != "abandoned" and key)
        protected.update(key for revision, key, model in revisions if key and
                         (revision not in abandoned_ids or revision in active_ids or model is not None))
        abandoned_keys = {key for key, _, status in replacements if status == "abandoned" and key}
        root_path = root.resolve()
        for entry in root_path.iterdir():
            if not GENERATED_KEY.fullmatch(entry.name) or entry.name in protected:
                continue
            try:
                info = entry.lstat()
                if not stat.S_ISREG(info.st_mode):
                    continue
                if entry.name not in abandoned_keys and info.st_mtime > cutoff:
                    continue
                entry.unlink()
                removed += 1
            except FileNotFoundError:
                continue
            except OSError:
                # Files locked by another process can be retried on the next pass.
                logger.warning("Could not remove a staged workspace file; cleanup will retry.")
    return removed
