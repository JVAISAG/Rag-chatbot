from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import os
import shutil
import logging
from contextlib import asynccontextmanager

from src.pipeline import RAGPipeline

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown: Clear documents and reset DB
    logging.info("Shutting down: Wiping all documents and vector DB...")
    if os.path.exists(pipeline.data_dir):
        shutil.rmtree(pipeline.data_dir)
        os.makedirs(pipeline.data_dir, exist_ok=True)
    try:
        pipeline.store.client.reset()
    except Exception as e:
        logging.warning(f"Failed to reset ChromaDB on shutdown: {e}")

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
        content={"detail": "Internal Server Error", "error_message": str(exc)},
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
    answer, sources = pipeline.query(
        user_query=req.query,
        history=req.history,
        use_hybrid=req.use_hybrid,
        use_reranking=req.use_reranking
    )
    return QueryResponse(answer=answer, sources=sources)

@app.post("/api/v1/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """
    Upload documents to the data directory for future indexing.
    """
    data_dir = pipeline.data_dir
    os.makedirs(data_dir, exist_ok=True)
    
    saved_files = []
    for file in files:
        file_path = os.path.join(data_dir, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        saved_files.append(file.filename)
        
    return {"message": f"Successfully uploaded {len(saved_files)} files.", "files": saved_files}

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
    Delete a specific file from the data directory and rebuild the index.
    """
    file_path = os.path.join(pipeline.data_dir, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        # Rebuild the index after deletion
        success = pipeline.build_index()
        return {"message": f"File {filename} deleted and index rebuilt.", "index_rebuilt": success}
    else:
        raise HTTPException(status_code=404, detail="File not found")
