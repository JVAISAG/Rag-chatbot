"""Opt-in real Ollama summary check using synthetic data and temporary SQLite."""
import sys
import argparse
import json
import os
from time import perf_counter
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from src.workspace.database import WorkspaceDatabase
from src.workspace.jobs.worker import Worker
from src.workspace.library.imports import stage_upload, extraction_handler
from src.workspace.library.indexing import indexing_handler
from src.workspace.library.summaries import enqueue_summary, summary_handler
from src.workspace.library import summaries
from src.workspace.models import Analysis, Base, Collection, Job, Source, SourceRevision, User


def main():
    if not __debug__:
        raise RuntimeError('Run without Python optimization so verification assertions stay active.')
    load_dotenv(ROOT / '.env', override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', help='Override the model for this synthetic check only.')
    parser.add_argument('--report', type=Path, help='Save synthetic results and elapsed time as JSON.')
    parser.add_argument('--multi-passage', action='store_true', help='Exercise three passage checkpoints and real summary synthesis.')
    args = parser.parse_args()
    if args.model:
        os.environ['OLLAMA_MODEL'] = args.model
    raw_outputs = []
    original_generate = summaries.generate_text
    def capture_synthetic_output(*positional, **keywords):
        text = original_generate(*positional, **keywords)
        raw_outputs.append(text)
        return text
    summaries.generate_text = capture_synthetic_output
    with TemporaryDirectory(prefix='summary-smoke-', dir=ROOT / '.cache') as temporary:
        root = Path(temporary)
        engine = create_engine('sqlite:///' + str(root / 'test.db'), connect_args={'check_same_thread': False})
        Base.metadata.create_all(engine)
        database = WorkspaceDatabase(engine_factory=lambda: engine)
        try:
            owner, collection = uuid.uuid4(), uuid.uuid4()
            with database.transaction() as session:
                session.add(User(id=owner, password_hash='synthetic'))
                session.flush()
                session.add(Collection(id=collection, owner_id=owner, name='Synthetic', normalized_name='synthetic'))
            source = stage_upload(database, root, owner, collection, 'study.txt', b'The study tested a classifier using a batch size of 64. The authors reported 90 percent accuracy on a synthetic dataset. The authors identified the small sample size as a limitation.')
            assert Worker(database, {'extract': extraction_handler(database, root)}).run_once()
            assert Worker(database, {'index': indexing_handler(database, embed=lambda texts: [[1.0] + [0.0] * 383 for _ in texts], split=lambda docs: [{'text': docs[0]['text'], 'metadata': {'page': 1}}])}).run_once()
            if args.multi_passage:
                # Controlled extracted pages of the same synthetic original.
                with database.transaction() as session:
                    revision = session.get(SourceRevision, session.get(Source, uuid.UUID(source['id'])).active_revision_id)
                    revision.pages = [{'page': number, 'text': text} for number, text in enumerate([
                        'The study tested a classifier using a batch size of 64.',
                        'The authors reported 90 percent accuracy on a synthetic dataset.',
                        'The authors identified the small sample size as a limitation.'], 1)]
            identity = enqueue_summary(database, owner, uuid.UUID(source['id']))['id']
            worker = Worker(database, {'summary': summary_handler(database)})
            started = perf_counter()
            for _ in range(6 if args.multi_passage else 1):
                assert worker.run_once()
                with database.transaction() as session:
                    analysis = session.get(Analysis, uuid.UUID(identity))
                    current_job = session.get(Job, analysis.job_id)
                    if analysis.status == 'completed' or current_job.status != 'pending' or current_job.attempts > 0:
                        break  # Do not retry failed inference automatically.
            elapsed = perf_counter() - started
            with database.transaction() as session:
                result = session.get(Analysis, uuid.UUID(identity))
                job = session.get(Job, result.job_id)
                report = {'model': result.model, 'elapsed_seconds': round(elapsed, 2),
                    'status': result.status, 'job_status': job.status, 'summary': result.result, 'raw_outputs': raw_outputs,
                    'scope': ('Three synthetic passages with map/reduce checkpoints.' if args.multi_passage else 'One synthetic passage.') + ' Elapsed time includes worker and local model calls.'}
                if args.report:
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
                print(json.dumps(report), flush=True)
                assert result.status == 'completed', 'The real summary did not complete.'
                assert any(result.result.values()), 'The model returned no findings.'
                print('PASS: real Ollama produced a saved summary with valid evidence references.')
        finally:
            database.close()


if __name__ == '__main__':
    main()
