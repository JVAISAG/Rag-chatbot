"""Collection-scoped BM25, pgvector, RRF, and cross-encoder retrieval."""
import uuid
from sqlalchemy import select
from src.embeddings.models import generate_embeddings
from src.retrieval.rrf import reciprocal_rank_fusion
from src.retrieval.reranker import CrossEncoderReranker
from src.workspace.library.indexing import MODEL
from src.workspace.models import Chunk, Collection, CollectionSource, Source, SourceRevision
from src.workspace.vectors import validate_vector
from src.workspace.library.sparse_cache import SPARSE_CACHE


def search_collection(database, owner: uuid.UUID, collection_id: uuid.UUID, query: str, *, embed=generate_embeddings, rerank=None, mode='reranked', source_ids=None):
    if mode not in {'dense', 'bm25', 'hybrid', 'reranked'}:
        raise ValueError('Unknown retrieval configuration.')
    selected = {uuid.UUID(str(value)) for value in source_ids} if source_ids is not None else None
    if selected is not None and (not selected or len(selected) > 20):
        raise ValueError('Choose between one and twenty sources.')
    def scope(session):
        statement = (select(SourceRevision.id).join(Source, Source.id == SourceRevision.source_id)
            .join(CollectionSource, CollectionSource.source_id == Source.id).join(Collection, Collection.id == CollectionSource.collection_id)
            .where(Collection.id == collection_id, Collection.owner_id == owner, Source.owner_id == owner,
                   Source.active_revision_id == SourceRevision.id, SourceRevision.embedding_model == MODEL))
        if selected is not None:
            statement = statement.where(Source.id.in_(selected))
        return list(session.scalars(statement))
    with database.transaction() as session:
        if session.scalar(select(Collection.id).where(Collection.id == collection_id, Collection.owner_id == owner)) is None:
            raise LookupError("Collection not found.")
        if selected is not None:
            owned = set(session.scalars(select(Source.id).join(CollectionSource, CollectionSource.source_id == Source.id)
                .where(CollectionSource.collection_id == collection_id, Source.owner_id == owner, Source.id.in_(selected))))
            if owned != selected:
                raise LookupError('Selected sources not found in this collection.')
        revisions = scope(session)
    if not revisions:
        return []
    vector = validate_vector(embed([query])[0]) if mode != 'bm25' else None
    with database.transaction() as session:
        # Snapshot membership is applied identically to both retrieval branches.
        allowed = set(revisions).intersection(scope(session))
        if not allowed:
            return []
        statement = select(Chunk, Source.filename, Source.id).join(SourceRevision, Chunk.revision_id == SourceRevision.id).join(Source, SourceRevision.source_id == Source.id)
        statement = statement.where(Chunk.revision_id.in_(allowed), Source.owner_id == owner)
        rows = session.execute(statement.order_by(Chunk.id)).all()
        dense_rows = session.execute(statement.order_by(Chunk.embedding.op("<=>")(vector), Chunk.id).limit(20)).all() if vector is not None else []
        def item(row):
            chunk, filename, source_id = row
            return {"id": str(chunk.id), "text": chunk.text, "metadata": {"source": filename, "source_id": str(source_id), "revision_id": str(chunk.revision_id), "page": chunk.page}}
        corpus, dense = [item(row) for row in rows], [item(row) for row in dense_rows]
    sparse = SPARSE_CACHE.get_or_build(owner, allowed, corpus).retrieve(query, 20) if mode != 'dense' else []
    fused = dense if mode == 'dense' else sparse if mode == 'bm25' else reciprocal_rank_fusion(dense, sparse)
    result = (rerank or CrossEncoderReranker().rerank)(query, fused, top_k=6) if mode == 'reranked' else fused[:6]
    with database.transaction() as session:
        still_allowed = {str(value) for value in scope(session)}
    return [item for item in result if item["metadata"]["revision_id"] in still_allowed]
