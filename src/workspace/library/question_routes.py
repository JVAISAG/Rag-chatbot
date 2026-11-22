"""Private conversation and asynchronous question endpoints."""
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from src.workspace.auth.dependencies import require_user
from src.workspace.auth.origins import require_trusted_origin
from src.workspace.library.questions import QuestionConflict, _scoped_chunks, enqueue_question
from src.workspace.library.routes import _collection_errors
from src.workspace.models import Collection, CollectionSource, Conversation, Job, QuestionTurn, Source

router = APIRouter(prefix="/api/v2", tags=["questions"])


class QuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def valid_question(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("Enter a question.")
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Question contains invalid Unicode.") from None
        return value.strip()


class ConversationScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=20)


@router.post("/collections/{collection_id}/conversations", status_code=201, dependencies=[Depends(require_trusted_origin)])
def create(request: Request, collection_id: uuid.UUID, details: ConversationScope | None = None, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        if session.scalar(select(Collection.id).where(Collection.id == collection_id, Collection.owner_id == owner)) is None:
            raise HTTPException(404, "Collection not found.")
        identity = uuid.uuid4()
        ids = set(details.source_ids) if details and details.source_ids is not None else None
        if ids is not None:
            owned = set(session.scalars(select(Source.id).join(CollectionSource, CollectionSource.source_id == Source.id)
                .where(Source.owner_id == owner, CollectionSource.collection_id == collection_id, Source.id.in_(ids))))
            if ids != owned:
                raise HTTPException(404, 'Selected sources not found in this collection.')
        session.add(Conversation(id=identity, owner_id=owner, collection_id=collection_id, source_ids=sorted(str(value) for value in ids) if ids is not None else None))
        return {"id": str(identity)}


@router.get("/collections/{collection_id}/conversations")
def list_owned(request: Request, response: Response, collection_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        if session.scalar(select(Collection.id).where(Collection.id == collection_id, Collection.owner_id == owner)) is None:
            raise HTTPException(404, "Collection not found.")
        rows = session.scalars(select(Conversation).where(Conversation.owner_id == owner, Conversation.collection_id == collection_id)
            .order_by(Conversation.created_at, Conversation.id)).all()
        result = [{"id": str(row.id), "created_at": row.created_at.isoformat(), "source_ids": row.source_ids} for row in rows]
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/conversations/{conversation_id}/messages", status_code=202, dependencies=[Depends(require_trusted_origin)])
def ask(request: Request, conversation_id: uuid.UUID, details: QuestionRequest, owner: uuid.UUID = Depends(require_user), idempotency_key: uuid.UUID | None = Header(default=None)):
    with _collection_errors():
        try:
            return enqueue_question(request.app.state.database, owner, conversation_id, details.question, idempotency_key)
        except LookupError:
            raise HTTPException(404, "Conversation not found.") from None
        except QuestionConflict:
            raise HTTPException(409, "Wait for the current question to finish.") from None


@router.get("/conversations/{conversation_id}")
def read(request: Request, response: Response, conversation_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        conversation = session.scalar(select(Conversation).where(Conversation.id == conversation_id, Conversation.owner_id == owner))
        if conversation is None:
            raise HTTPException(404, "Conversation not found.")
        rows = session.execute(select(QuestionTurn, Job.status).join(Job, Job.id == QuestionTurn.job_id)
            .where(QuestionTurn.conversation_id == conversation_id).order_by(QuestionTurn.created_at, QuestionTurn.id)).all()
        turns = []
        for turn, job_status in rows:
            evidence = turn.evidence or []
            allowed = _scoped_chunks(session, owner, conversation.collection_id, [item["id"] for item in evidence], source_ids=conversation.source_ids)
            references = [{"number": number, "text": item["text"] if item["id"] in allowed else "", "metadata": item["metadata"], "available": item["id"] in allowed} for number, item in enumerate(evidence, 1)]
            state = "failed" if turn.status == "pending" and job_status == "failed" else turn.status
            turns.append({"id": str(turn.id), "question": turn.question, "answer": turn.answer if turn.status != "pending" else None,
                "status": state, "evidence": references if turn.status != "pending" else [], "model": turn.model, "timings": turn.timings})
        result = {"id": str(conversation.id), "turns": turns}
    response.headers["Cache-Control"] = "no-store"
    return result
