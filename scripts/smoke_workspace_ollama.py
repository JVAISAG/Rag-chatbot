"""Opt-in real Ollama answer smoke check using isolated synthetic evidence.

Exercises the durable answer worker, bounded prompt, citation validation, and
saved evidence. Retrieval is a fixed fixture; PostgreSQL search is tested
separately. Does not connect to or modify the workspace database or files.
"""

import json
import re
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
from sqlalchemy import create_engine, event

from src.workspace.database import DEFAULT_ENV_FILE, WorkspaceDatabase
from src.workspace.jobs.worker import Worker
from src.workspace.library.questions import answer_handler, enqueue_question
from src.workspace.models import Base, Chunk, Collection, CollectionSource, Conversation, Job, QuestionTurn, Source, SourceRevision, User


def main():
    load_dotenv(DEFAULT_ENV_FILE, override=False)
    with TemporaryDirectory(prefix="workspace-ollama-smoke-") as temporary:
        engine = create_engine(f"sqlite+pysqlite:///{Path(temporary).as_posix()}/smoke.sqlite", connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        database = WorkspaceDatabase(engine_factory=lambda: engine)
        try:
            Base.metadata.create_all(engine)
            owner, collection, conversation, source, revision, chunk, import_job = [uuid.uuid4() for _ in range(7)]
            text = "The synthetic test study trained a classifier with a batch size of 64 for 16 epochs."
            with database.transaction() as session:
                session.add(User(id=owner, password_hash="not-a-sign-in-account"))
                session.flush()
                session.add_all([
                    Collection(id=collection, owner_id=owner, name="Synthetic test", normalized_name="synthetic test"),
                    Job(id=import_job, owner_id=owner, kind="extract", payload={}, status="completed"),
                ])
                session.flush()
                session.add_all([
                    Source(id=source, owner_id=owner, filename="synthetic-study.txt", content_hash="0" * 64, storage_key="unused", job_id=import_job),
                    Conversation(id=conversation, owner_id=owner, collection_id=collection),
                ])
                session.flush()
                session.add_all([
                    SourceRevision(id=revision, source_id=source, pages=[{"text": text, "page": 1}], extraction_version="smoke-v1"),
                    CollectionSource(collection_id=collection, source_id=source),
                ])
                session.flush()
                session.add(Chunk(id=chunk, revision_id=revision, ordinal=0, page=1, text=text, embedding=[1.0] + [0.0] * 383))
            queued = enqueue_question(database, owner, conversation, "What batch size and how many training epochs did the study use?")
            handler = answer_handler(database, retrieve=lambda *args: [{"id": str(chunk)}])
            print("Running the real Ollama answer worker...", flush=True)
            Worker(database, {"answer": handler}).run_once()
            with database.transaction() as session:
                turn = session.get(QuestionTurn, uuid.UUID(queued["id"]))
                job = session.get(Job, uuid.UUID(queued["job_id"]))
                if job.status != "completed" or turn.status != "completed":
                    raise RuntimeError(f"Live answer check failed (job={job.status}, answer={turn.status}). Check Ollama, its model, and timeout settings.")
                references = [int(value) for value in re.findall(r'\[(\d+)\]', turn.answer)]
                if not references or any(not 1 <= value <= len(turn.evidence) for value in references) or not all(value in turn.answer for value in ("64", "16")):
                    print(json.dumps({'status': 'failed', 'model': turn.model, 'answer': turn.answer,
                        'evidence_count': len(turn.evidence)}, indent=2), flush=True)
                    raise RuntimeError("Live answer did not cite and reproduce the synthetic study's settings.")
                if len(turn.evidence) != 1 or turn.evidence[0]["id"] != str(chunk) or turn.evidence[0]["text"] != text:
                    raise RuntimeError("Saved evidence did not match the supplied synthetic study.")
                print(json.dumps({"status": "passed", "model": turn.model, "answer": turn.answer, "evidence_count": len(turn.evidence)}, indent=2))
        finally:
            database.close()


if __name__ == "__main__":
    main()
