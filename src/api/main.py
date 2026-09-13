from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import os
import shutil
import logging
import uuid
from contextlib import asynccontextmanager
from contextlib import asynccontextmanager

from src.pipeline import RAGPipeline

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    logging.info("Shutting down API server...")

app = FastAPI(
    title="Agentic RAG API", 
    description="Production-grade Agentic RAG Platform API",
    version="1.0.0",
    lifespan=lifespan
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled exception at {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "The chatbot could not process your request. Please try again later."},
    )

# Global pipeline instance initialized lazily
pipeline = RAGPipeline(llm_model="llama3.2")

class QueryRequest(BaseModel):
    query: str
    history: Optional[List[Dict[str, str]]] = None
    use_hybrid: bool = False
    use_reranking: bool = False

class QueryResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]

@app.post("/api/v1/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest):
    """
    Submit a query to the agentic RAG pipeline.
    The router will automatically determine intent (small talk, web search, summarization, direct knowledge).
    """
    if len(req.query) > 1000:
        raise HTTPException(status_code=400, detail="Query too long. Maximum 1000 characters allowed.")
        
    answer, sources = pipeline.query(
        user_query=req.query,
        history=req.history,
        use_hybrid=req.use_hybrid,
        use_reranking=req.use_reranking
    )
    return QueryResponse(answer=answer, sources=sources)

MAX_UPLOAD_MB = 10
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

@app.post("/api/v1/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """
    Upload documents to the data directory and ingest them incrementally.
    """
    data_dir = pipeline.data_dir
    os.makedirs(data_dir, exist_ok=True)
    
    saved_files = []
    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")
            
        file.file.seek(0, os.SEEK_END)
        size_bytes = file.file.tell()
        file.file.seek(0)
        
        if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"File {file.filename} exceeds {MAX_UPLOAD_MB}MB limit.")
            
        # Generate safe server-side filename
        safe_filename = f"{uuid.uuid4()}{ext}"
        file_path = os.path.join(data_dir, safe_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Incrementally ingest
        # We pass the original filename as the source for frontend tracking
        pipeline.ingest_file(file_path, file.filename)
        saved_files.append(file.filename)
        
    return {"message": f"Successfully uploaded and ingested {len(saved_files)} files.", "files": saved_files}

@app.post("/api/v1/index")
def rebuild_index():
    """
    Rebuild the vector store index from the documents in the data directory.
    """
    success = pipeline.build_index()
        
    if success:
        return {"message": "Index rebuilt successfully."}
    else:
        raise HTTPException(status_code=400, detail="Failed to build index. Ensure data folder is not empty.")

@app.delete("/api/v1/file/{filename}")
def delete_file(filename: str):
    """
    Delete a specific file incrementally from the index.
    """
    # Incrementally remove from index
    success = pipeline.remove_file(filename)
    
    # We don't necessarily delete the safe_filename from disk here unless we map it back,
    # but the chunks are gone from the VectorDB and BM25, which is the primary concern.
    
    if success:
        return {"message": f"File {filename} removed from index successfully."}
    else:
        raise HTTPException(status_code=400, detail="Failed to remove file from index.")
