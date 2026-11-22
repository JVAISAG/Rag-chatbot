"""Reproducible source-level retrieval evaluation in an isolated PostgreSQL DB."""
import json
import os
from importlib.metadata import version
from math import log2
from pathlib import Path
import platform
from tempfile import TemporaryDirectory
from time import perf_counter, sleep
import uuid
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from src.workspace.database import WorkspaceDatabase
from src.workspace.jobs.worker import Worker
from src.workspace.library.imports import stage_upload, extraction_handler
from src.workspace.library.indexing import indexing_handler
from src.workspace.library.search import search_collection
from src.workspace.models import Collection, Source, User
from eval.workspace_dataset import load_dataset, dataset_fingerprint
from src.generation.client import setting

ROOT = Path(__file__).resolve().parents[1]


def scores(expected, ranked, k=3):
    relevant = set(expected)
    unique = list(dict.fromkeys(ranked))[:k]
    if not relevant:
        raise ValueError('Unanswerable questions require separate abstention evaluation.')
    recall = len(relevant.intersection(unique)) / len(relevant)
    reciprocal = next((1 / (index + 1) for index, item in enumerate(unique) if item in relevant), 0)
    dcg = sum(1 / log2(index + 2) for index, item in enumerate(unique) if item in relevant)
    ideal = sum(1 / log2(index + 2) for index in range(min(k, len(relevant))))
    return {'recall_at_3': recall, 'mrr_at_3': reciprocal, 'ndcg_at_3': dcg / ideal}


def evaluate(url, report_path, *, generate_answers=False, score_retrieval=True, dataset_path=None):
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    dataset = load_dataset(dataset_path or ROOT / 'eval/workspace_set.json')
    engine = create_engine(url, poolclass=NullPool)
    database = WorkspaceDatabase(engine_factory=lambda: engine)
    try:
        with engine.begin() as connection:
            config = Config(str(ROOT / 'workspace.alembic.ini'))
            config.attributes['connection'] = connection
            command.upgrade(config, 'head')
        with TemporaryDirectory(prefix='workspace-eval-', dir=ROOT / '.cache') as temporary:
            storage = Path(temporary)
            owner, collection = uuid.uuid4(), uuid.uuid4()
            with database.transaction() as session:
                session.add(User(id=owner, password_hash='synthetic-evaluation'))
                session.flush()
                session.add(Collection(id=collection, owner_id=owner, name='Evaluation', normalized_name='evaluation'))
            aliases = {}
            worker = Worker(database, {'extract': extraction_handler(database, storage), 'index': indexing_handler(database)})
            for source in dataset['sources']:
                print(f"Indexing synthetic source {source['id']}...", flush=True)
                imported = stage_upload(database, storage, owner, collection, source['id'] + '.txt', source['text'].encode('utf-8'))
                aliases[imported['id']] = source['id']
                if not worker.run_once() or not worker.run_once():
                    raise RuntimeError('Evaluation indexing did not complete.')
                with database.transaction() as session:
                    if session.get(Source, uuid.UUID(imported['id'])).active_revision_id is None:
                        raise RuntimeError('Evaluation source is not indexed. Check cached models and worker errors.')
            # Warm model loading separately; timed queries below are warm runs.
            search_collection(database, owner, collection, 'synthetic warmup')
            results = []
            modes = ('dense', 'bm25', 'hybrid', 'reranked') if score_retrieval else ()
            for mode in modes:
                print(f'Evaluating {mode}...', flush=True)
                for question in dataset['questions']:
                    if not question['sources']:
                        continue
                    started = perf_counter()
                    hits = search_collection(database, owner, collection, question['question'], mode=mode)
                    elapsed = perf_counter() - started
                    ranked = [aliases[item['metadata']['source_id']] for item in hits]
                    results.append({'mode': mode, 'question_id': question['id'], 'expected': question['sources'],
                        'ranked_sources': ranked, 'elapsed_seconds': elapsed, **scores(question['sources'], ranked)})
            aggregate = {}
            for mode in modes:
                rows = [item for item in results if item['mode'] == mode]
                aggregate[mode] = {key: sum(row[key] for row in rows) / len(rows) for key in ('recall_at_3', 'mrr_at_3', 'ndcg_at_3', 'elapsed_seconds')}
            answers = []
            if generate_answers:
                from src.workspace.library.questions import answer_handler, enqueue_question
                from src.workspace.models import Conversation, Job, QuestionTurn
                answer_worker = Worker(database, {'answer': answer_handler(database)})
                for question in dataset['questions']:
                    print(f"Generating evaluation answer {question['id']}...", flush=True)
                    conversation = uuid.uuid4()
                    with database.transaction() as session:
                        session.add(Conversation(id=conversation, owner_id=owner, collection_id=collection))
                    queued = enqueue_question(database, owner, conversation, question['question'])
                    started = perf_counter()
                    # A transient failure leaves the same job queued for retry.
                    # Do not advance to another question and accidentally claim
                    # the preceding question's retry as if it were the new one.
                    while True:
                        processed = answer_worker.run_once()
                        with database.transaction() as session:
                            job_status = session.get(Job, uuid.UUID(queued['job_id'])).status
                        if job_status in {'completed', 'failed'}:
                            break
                        if perf_counter() - started > 600:
                            raise RuntimeError('Answer evaluation did not reach a terminal job state.')
                        if not processed:
                            sleep(0.25)
                    with database.transaction() as session:
                        turn = session.get(QuestionTurn, uuid.UUID(queued['id']))
                        answers.append({'question_id': question['id'], 'question': question['question'], 'expected': question['answer'],
                            'status': 'failed' if job_status == 'failed' else turn.status, 'answer': turn.answer, 'model': turn.model,
                            'elapsed_seconds': perf_counter() - started, 'reference_count': len(turn.evidence or []),
                            'evidence': [{'number': index + 1, 'source': aliases.get(item['metadata']['source_id']),
                                'text': item['text']} for index, item in enumerate(turn.evidence or [])],
                            'timings': turn.timings, 'requires_semantic_review': True})
                    # Preserve completed outputs if a long local run is interrupted.
                    report_path.write_text(json.dumps({'complete': False, 'scope': dataset['scope'], 'dataset_sha256': dataset_fingerprint(dataset),
                        'question_count': len(dataset['questions']), 'answers': answers}, indent=2), encoding='utf-8')
                    if job_status == 'failed':
                        raise RuntimeError('A model job failed. The partial report was preserved; restore the model service before retrying.')
            report = {'complete': True, 'scope': dataset['scope'], 'dataset_sha256': dataset_fingerprint(dataset), 'question_count': len(dataset['questions']),
                'retrieval_question_count': len(results) // 4, 'retrieval_evaluated': score_retrieval,
                'unanswerable_questions_not_scored_for_retrieval': sum(not question['sources'] for question in dataset['questions']),
                'generation_evaluated': generate_answers, 'answers': answers, 'timing': 'Warm retrieval; excludes model loading and generation. Answer timings are recorded separately.',
                'hardware': {'platform': platform.platform(), 'processor': platform.processor()},
                'models': {'embedding': 'all-MiniLM-L6-v2', 'reranker': 'cross-encoder/ms-marco-MiniLM-L-6-v2',
                    'generation_context_tokens': int(setting('OLLAMA_CONTEXT_TOKENS', '2048')) if generate_answers else None,
                    'sentence_transformers_version': version('sentence-transformers')}, 'aggregate': aggregate, 'results': results}
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(aggregate, indent=2), flush=True)
            print(f'Saved synthetic evaluation report: {report_path}', flush=True)
    finally:
        database.close()
