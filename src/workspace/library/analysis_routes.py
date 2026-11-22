"""Private saved source summaries and progress."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from src.workspace.auth.dependencies import require_user
from src.workspace.auth.origins import require_trusted_origin
from src.workspace.library.routes import _collection_errors
from src.workspace.library.summaries import enqueue_summary
from src.workspace.models import Analysis, Job, Source

router = APIRouter(prefix='/api/v2', tags=['analyses'])


@router.post('/sources/{source_id}/summaries', status_code=202, dependencies=[Depends(require_trusted_origin)])
def create_summary(request: Request, source_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors():
        try:
            return enqueue_summary(request.app.state.database, owner, source_id)
        except LookupError:
            raise HTTPException(404, 'Indexed source not found or its revision changed.') from None
        except ValueError:
            raise HTTPException(409, 'No extracted text is available.') from None


@router.get('/sources/{source_id}/summaries')
def list_summaries(request: Request, response: Response, source_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        if session.scalar(select(Source.id).where(Source.id == source_id, Source.owner_id == owner)) is None:
            raise HTTPException(404, 'Source not found.')
        rows = session.scalars(select(Analysis).where(Analysis.source_id == source_id, Analysis.owner_id == owner).order_by(Analysis.created_at.desc(), Analysis.id.desc())).all()
        result = [{'id': str(row.id), 'revision_id': str(row.revision_id) if row.revision_id else None, 'created_at': row.created_at.isoformat()} for row in rows]
    response.headers['Cache-Control'] = 'no-store'
    return result


@router.get('/analyses/{analysis_id}')
def read_summary(request: Request, response: Response, analysis_id: uuid.UUID, owner: uuid.UUID = Depends(require_user)):
    with _collection_errors(), request.app.state.database.transaction() as session:
        row = session.scalar(select(Analysis).where(Analysis.id == analysis_id, Analysis.owner_id == owner))
        if row is None:
            raise HTTPException(404, 'Analysis not found.')
        job = session.get(Job, row.job_id)
        available = row.source_id is not None and row.revision_id is not None
        status = 'unavailable' if not available else ('failed' if row.status == 'pending' and job.status == 'failed' else row.status)
        result = {'id': str(row.id), 'revision_id': str(row.revision_id) if available else None, 'status': status,
            'processed': row.state['cursor'], 'total': len(row.state['blocks']), 'stage': row.state['stage'],
            'result': row.result if available and status == 'completed' else None,
            'evidence': row.state['blocks'] if available and status == 'completed' else [],
            'model': row.model, 'prompt_version': row.prompt_version}
    response.headers['Cache-Control'] = 'no-store'
    return result
