"""Private collection endpoints."""

from contextlib import contextmanager
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError

from src.workspace.auth.dependencies import require_user
from src.workspace.auth.origins import require_trusted_origin
from src.workspace.database import DatabaseConfigurationError
from src.workspace.library.collections import (
    CollectionCreate,
    CollectionNameUnavailable,
    CollectionHasNotes,
    CollectionNotFound,
    CollectionResponse,
    CollectionUpdate,
    create_collection,
    delete_collection,
    get_collection,
    list_collections,
    update_collection,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/collections", tags=["collections"])


@contextmanager
def _collection_errors():
    try:
        yield
    except CollectionNotFound:
        raise HTTPException(status_code=404, detail="Collection not found.", headers={"Cache-Control": "no-store"}) from None
    except CollectionNameUnavailable:
        raise HTTPException(status_code=409, detail="A collection with that name already exists.", headers={"Cache-Control": "no-store"}) from None
    except CollectionHasNotes:
        raise HTTPException(status_code=409, detail="This collection has saved research notes. Export any notes you want to keep, then delete the notes before deleting the collection.", headers={"Cache-Control": "no-store"}) from None
    except (DatabaseConfigurationError, SQLAlchemyError, OSError):
        logger.warning("Workspace collections could not access the database.")
        raise HTTPException(status_code=503, detail="Collections are unavailable right now.", headers={"Cache-Control": "no-store"}) from None


@router.get("", response_model=list[CollectionResponse])
def list_owned(request: Request, response: Response, user_id: uuid.UUID = Depends(require_user)) -> list[CollectionResponse]:
    with _collection_errors():
        result = list_collections(request.app.state.database, user_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CollectionResponse,
             dependencies=[Depends(require_trusted_origin)])
def create(request: Request, response: Response, details: CollectionCreate,
           user_id: uuid.UUID = Depends(require_user)) -> CollectionResponse:
    with _collection_errors():
        result = create_collection(request.app.state.database, user_id, details)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/{collection_id}", response_model=CollectionResponse)
def get_owned(request: Request, response: Response, collection_id: uuid.UUID,
              user_id: uuid.UUID = Depends(require_user)) -> CollectionResponse:
    with _collection_errors():
        result = get_collection(request.app.state.database, user_id, collection_id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.patch("/{collection_id}", response_model=CollectionResponse,
              dependencies=[Depends(require_trusted_origin)])
def update(request: Request, response: Response, collection_id: uuid.UUID, details: CollectionUpdate,
           user_id: uuid.UUID = Depends(require_user)) -> CollectionResponse:
    with _collection_errors():
        result = update_collection(request.app.state.database, user_id, collection_id, details)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_trusted_origin)])
def delete(request: Request, collection_id: uuid.UUID, user_id: uuid.UUID = Depends(require_user)) -> Response:
    with _collection_errors():
        delete_collection(request.app.state.database, user_id, collection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})
