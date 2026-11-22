"""Persist and generate private, evidence-backed answers."""
from contextlib import ExitStack
from datetime import datetime, timezone
import os
import uuid
from time import perf_counter
from sqlalchemy import select
from src.generation.client import DEFAULT_MODEL, generate_text, setting
from src.generation.llm import LLMGenerator
from src.workspace.library.answer_format import (ANSWER_SYSTEM_PROMPT, IdentifierMismatch,
    answer_prompt, answer_schema, decode_answer, quote_prompt, quote_schema, decode_quote)
from src.errors import ModelUnavailableError
from src.workspace.jobs.worker import LeaseLost, PermanentJobError
from src.workspace.library.search import search_collection
from src.workspace.models import Chunk, Collection, CollectionSource, Conversation, Job, QuestionTurn, Source, SourceRevision


ANSWER_PROMPT_VERSION = "qa-v4"


class QuestionConflict(ValueError):
    """A conversation already has an active or conflicting request."""


def enqueue_question(database, owner, conversation_id, question, request_key=None):
    with database.transaction() as session:
        conversation = session.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == owner).with_for_update())
        if conversation is None or conversation.collection_id is None:
            raise LookupError("Conversation not found.")
        if request_key is not None:
            existing = session.scalar(select(QuestionTurn).where(QuestionTurn.conversation_id == conversation_id, QuestionTurn.request_key == request_key))
            if existing is not None:
                if existing.question != question:
                    raise QuestionConflict("Request key was already used with a different question.")
                return {"id": str(existing.id), "job_id": str(existing.job_id)}
        active = session.scalar(select(QuestionTurn.id).join(Job, Job.id == QuestionTurn.job_id).where(
            QuestionTurn.conversation_id == conversation_id, QuestionTurn.status == "pending", Job.status.in_(["pending", "running"])))
        if active is not None:
            raise QuestionConflict("Wait for the current question to finish.")
        job_id, turn_id = uuid.uuid4(), uuid.uuid4()
        session.add(Job(id=job_id, owner_id=owner, kind="answer", payload={"turn_id": str(turn_id)}))
        session.flush()
        session.add(QuestionTurn(id=turn_id, conversation_id=conversation_id, job_id=job_id, question=question, request_key=request_key))
        return {"id": str(turn_id), "job_id": str(job_id)}


def _live_job(session, claimed):
    job = session.scalar(select(Job).where(Job.id == claimed.id).with_for_update())
    expiry = job.lease_expires_at if job else None
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if job is None or job.status != "running" or job.lease_token != claimed.lease_token or expiry is None or expiry <= datetime.now(timezone.utc):
        raise LeaseLost("The answer lease expired.")


def _scoped_chunks(session, owner, collection_id, ids, *, lock=False, source_ids=None):
    if not ids or collection_id is None:
        return {}
    statement = (select(Chunk, Source, SourceRevision.filename).join(SourceRevision, SourceRevision.id == Chunk.revision_id)
        .join(Source, Source.id == SourceRevision.source_id).join(CollectionSource, CollectionSource.source_id == Source.id)
        .join(Collection, Collection.id == CollectionSource.collection_id)
        .where(Chunk.id.in_([uuid.UUID(value) for value in ids]), Collection.id == collection_id,
               Collection.owner_id == owner, Source.owner_id == owner))
    if lock:
        statement = statement.with_for_update(read=True, of=Source)
    if source_ids is not None:
        statement = statement.where(Source.id.in_([uuid.UUID(value) for value in source_ids]))
    rows = session.execute(statement).all()
    return {str(chunk.id): {"id": str(chunk.id), "text": chunk.text, "metadata": {
        "source": filename or source.filename, "source_id": str(source.id), "revision_id": str(chunk.revision_id), "page": chunk.page}} for chunk, source, filename in rows}


def answer_from_evidence(generator, question, selected, model, *, generate=None):
    """Shared generation/citation gate for the worker and replay evaluation."""
    if not selected:
        return 'I could not find supporting evidence in this collection.', 'no_evidence'
    def invoke(prompt):
        return generate(prompt) if generate else generate_text(generator.client, model, prompt,
            system=ANSWER_SYSTEM_PROMPT, context_tokens=generator.context_tokens,
            response_format=answer_schema(len(selected)))
    result, feedback = None, ''
    for repair in (False, True):
        prompt = answer_prompt(question, selected, repair=repair, feedback=feedback)
        raw = invoke(prompt)
        try:
            result = decode_answer(raw, len(selected), selected=selected)
            break
        except IdentifierMismatch as exc:
            feedback = str(exc)
        except (ValueError, TypeError):
            continue
    if result is not None:
        if result[1] == 'insufficient_evidence':
            # Verbatim extraction gives a refusing model a narrower task. Never
            # turn an excerpt into an unlabeled, supposedly complete answer.
            for index in range(min(3, len(selected))):
                try:
                    raw = generate(quote_prompt(question, selected, index)) if generate else generate_text(
                        generator.client, model, quote_prompt(question, selected, index),
                        system=ANSWER_SYSTEM_PROMPT, context_tokens=generator.context_tokens,
                        response_format=quote_schema(index + 1))
                    focused = decode_quote(raw, selected, index)
                    if focused is not None:
                        return focused
                except (ValueError, TypeError):
                    continue
                except ModelUnavailableError:
                    break  # Preserve the valid abstention if its optional check fails.
        return result
    return 'I could not produce an answer with valid supporting citations.', 'unsupported'


def answer_handler(database, *, retrieve=search_collection, generator_factory=None, generate=None):
    def run(claimed, context, resources):
        attempt_started = perf_counter()
        turn_id = uuid.UUID(claimed.payload["turn_id"])
        with database.transaction() as session:
            row = session.execute(select(QuestionTurn, Conversation).join(Conversation, Conversation.id == QuestionTurn.conversation_id)
                .where(QuestionTurn.id == turn_id, QuestionTurn.job_id == claimed.id, Conversation.owner_id == claimed.owner_id)).one_or_none()
            if row is None:
                raise PermanentJobError("Question unavailable.")
            turn, conversation = row
            if turn.status != "pending":
                return
            question, collection_id, snapshot, retrieval_query = turn.question, conversation.collection_id, turn.evidence, turn.retrieval_query
            source_ids = conversation.source_ids
            timings = dict(turn.timings or {})
            if 'initial_queue_seconds' not in timings:
                queued_at = turn.created_at
                if queued_at.tzinfo is None:
                    queued_at = queued_at.replace(tzinfo=timezone.utc)
                timings['initial_queue_seconds'] = round(max(0, (datetime.now(timezone.utc) - queued_at).total_seconds()), 4)
                # Commit before model loading/retrieval so retries cannot turn a
                # failed attempt's processing time into apparent queue wait.
                turn.timings = dict(timings)
            previous = session.scalars(select(QuestionTurn).where(QuestionTurn.conversation_id == conversation.id,
                QuestionTurn.status.in_(['completed', 'insufficient_evidence', 'quoted_evidence'])).order_by(QuestionTurn.created_at.desc(), QuestionTurn.id.desc()).limit(3)).all()
            history = [message for old in reversed(previous) for message in [{"role": "user", "content": old.question}, {"role": "assistant", "content": old.answer or ""}]]
        if collection_id is None:
            raise PermanentJobError("Collection unavailable.")
        model = setting("OLLAMA_MODEL", DEFAULT_MODEL)
        generator = generator_factory() if generator_factory else LLMGenerator(model_name=model)
        if generator_factory is None:
            resources.callback(generator.client.close)
        context.ensure_active()
        if snapshot is None:
            retrieval_started = perf_counter()
            retrieval_query = generator.condense_query(question, history) if history else question
            try:
                hits = retrieve(database, claimed.owner_id, collection_id, retrieval_query, **({'source_ids': source_ids} if source_ids is not None else {}))
            except LookupError:
                raise PermanentJobError("Collection unavailable.") from None
            with database.transaction() as session:
                allowed = _scoped_chunks(session, claimed.owner_id, collection_id, [item["id"] for item in hits], source_ids=source_ids)
            hits = [allowed[item["id"]] for item in hits if item["id"] in allowed]
            _, snapshot = generator._prepare_context(retrieval_query, hits)
            timings['retrieval_and_rewrite_seconds'] = round(perf_counter() - retrieval_started, 4)
            with database.transaction() as session:
                _live_job(session, claimed)
                turn = session.get(QuestionTurn, turn_id)
                if turn is None:
                    raise PermanentJobError("Question unavailable.")
                turn.evidence, turn.retrieval_query, turn.model = snapshot, retrieval_query, model
                turn.timings = dict(timings)
        # The exact persisted evidence set is reused after transient failures.
        with database.transaction() as session:
            _live_job(session, claimed)
            allowed = _scoped_chunks(session, claimed.owner_id, collection_id, [item["id"] for item in snapshot], source_ids=source_ids)
            turn = session.get(QuestionTurn, turn_id)
            if turn is None:
                raise PermanentJobError("Question unavailable.")
            turn.prompt_version, turn.model = ANSWER_PROMPT_VERSION, model
        unavailable = any(item["id"] not in allowed for item in snapshot)
        answer_question = retrieval_query or question
        _, selected = generator._prepare_context(answer_question, [] if unavailable else snapshot)
        if unavailable:
            answer, state = "Supporting evidence is no longer available in this collection.", "unavailable"
        elif not selected:
            answer, state = "I could not find supporting evidence in this collection.", "no_evidence"
        else:
            generation_started = perf_counter()
            answer, state = answer_from_evidence(generator, answer_question, selected, model, generate=generate)
            timings['generation_and_repair_seconds'] = round(perf_counter() - generation_started, 4)
        context.ensure_active()
        with database.transaction() as session:
            _live_job(session, claimed)
            turn = session.scalar(select(QuestionTurn).where(QuestionTurn.id == turn_id).with_for_update())
            if turn is None:
                raise PermanentJobError("Question unavailable.")
            conversation = session.get(Conversation, turn.conversation_id)
            allowed = _scoped_chunks(session, claimed.owner_id, conversation.collection_id, [item["id"] for item in selected], lock=True, source_ids=conversation.source_ids)
            if any(item["id"] not in allowed for item in selected) or conversation.collection_id != collection_id:
                answer, state, selected = "Supporting evidence is no longer available in this collection.", "unavailable", []
            turn.answer, turn.status, turn.evidence, turn.model = answer, state, selected, model
            timings['last_attempt_seconds'] = round(perf_counter() - attempt_started, 4)
            turn.timings = timings
    def handle(claimed, context):
        with ExitStack() as resources:
            run(claimed, context, resources)
    return handle
