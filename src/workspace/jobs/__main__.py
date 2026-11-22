"""Run the local extraction worker: python -m src.workspace.jobs."""
from threading import Event
import logging
from dotenv import load_dotenv
from src.workspace.database import DEFAULT_ENV_FILE, WorkspaceDatabase
from src.workspace.jobs.worker import Worker
from src.workspace.library.imports import DEFAULT_STORAGE, extraction_handler
from src.workspace.library.cleanup import reconcile_storage
from src.workspace.library.deletion import cleanup_source_handler
from src.workspace.library.indexing import enqueue_missing_indexes, indexing_handler
from src.workspace.library.questions import answer_handler
from src.workspace.library.summaries import summary_handler
from src.workspace.status import record_heartbeat
from src.workspace.library.url_imports import url_import_handler, url_refresh_handler


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    load_dotenv(DEFAULT_ENV_FILE, override=False)
    database = WorkspaceDatabase()
    try:
        database.check()
        enqueue_missing_indexes(database)
        handlers = {"summary": summary_handler(database), "cleanup_source": cleanup_source_handler(database, DEFAULT_STORAGE), "extract": extraction_handler(database, DEFAULT_STORAGE), "index": indexing_handler(database), "answer": answer_handler(database), "url_import": url_import_handler(database, DEFAULT_STORAGE), "url_refresh": url_refresh_handler(database, DEFAULT_STORAGE)}
        Worker(database, handlers, worker_heartbeat=record_heartbeat).run(
            Event(), maintenance=lambda: reconcile_storage(database, DEFAULT_STORAGE))
    except KeyboardInterrupt:
        pass
    finally:
        database.close()


if __name__ == "__main__":
    main()
