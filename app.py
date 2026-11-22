import streamlit as st
import os
import requests
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

# API Base URL
API_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "360"))

def safe_api_request(method: str, endpoint: str, **kwargs):
    """Centralized error handling for API requests."""
    try:
        kwargs.setdefault("timeout", (5, REQUEST_TIMEOUT))
        if method.upper() == "POST":
            res = requests.post(f"{API_URL}{endpoint}", **kwargs)
        elif method.upper() == "GET":
            res = requests.get(f"{API_URL}{endpoint}", **kwargs)
        elif method.upper() == "DELETE":
            res = requests.delete(f"{API_URL}{endpoint}", **kwargs)
        else:
            st.error(f"Unsupported HTTP method: {method}")
            return None
            
        if res.ok:
            try:
                data = res.json()
            except ValueError:
                st.error("The backend returned an invalid response.")
                return None
            if not isinstance(data, dict):
                st.error("The backend returned an invalid response.")
                return None
            for error in data.get("errors", []):
                st.error(f"{error['file']}: {error['detail']}")
            return data
                
        # Handle non-200 responses
        try:
            error_data = res.json()
            err_msg = error_data.get("detail", error_data.get("errors", res.text))
        except Exception:
            err_msg = res.text
            
        st.error(f"API Error ({res.status_code}): {err_msg}")
        return None
        
    except requests.exceptions.ConnectionError:
        st.error("Failed to connect to backend. Is the FastAPI server running?")
    except requests.exceptions.Timeout:
        st.error("Request timed out. The backend might be overloaded.")
    except Exception as e:
        st.error(f"An unexpected error occurred: {e}")
        
    return None


def render_sources(sources):
    with st.expander("🔍 View sources"):
        for source in sources:
            metadata = source.get("metadata", {})
            name = source.get("source", metadata.get("source", "Unknown"))
            citation = source.get("citation", "")
            page = f", page {metadata['page']}" if "page" in metadata else ""
            st.markdown(f"**{citation} {name}{page}**")
            st.text(source.get("text_snippet", source.get("text", "")))

st.set_page_config(page_title="Personal Agentic RAG", layout="wide", initial_sidebar_state="expanded")

# --- Custom Styling (Premium Dark Mode + Glassmorphism) ---
st.markdown("""
<style>
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}
/* Main App Background */
.stApp {
    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
    color: #f8fafc;
}
/* Sidebar Glassmorphism */
[data-testid="stSidebar"] {
    background: rgba(15, 23, 42, 0.4) !important;
    backdrop-filter: blur(16px);
    border-right: 1px solid rgba(255, 255, 255, 0.05);
}
/* Buttons */
.stButton > button {
    background: linear-gradient(90deg, #3b82f6 0%, #8b5cf6 100%);
    color: white !important;
    border: none !important;
    border-radius: 8px;
    font-weight: 600;
    transition: all 0.3s ease !important;
}
.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(139, 92, 246, 0.4);
}
/* Chat Messages */
[data-testid="stChatMessage"] {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 12px;
    padding: 1.5rem;
    backdrop-filter: blur(10px);
    margin-bottom: 1.5rem;
    transition: transform 0.2s ease;
}
[data-testid="stChatMessage"]:hover {
    transform: scale(1.01);
}
/* Expanders */
.streamlit-expanderHeader {
    background: rgba(255, 255, 255, 0.05);
    border-radius: 6px;
}
/* Headers */
h1, h2, h3 {
    background: -webkit-linear-gradient(45deg, #60a5fa, #c084fc);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
</style>
""", unsafe_allow_html=True)

st.title("✨ Agentic RAG Platform")
st.markdown("Ask anything. Our intelligent router will route between Small Talk, Local Knowledge, Summarization, and Live Web Search.")

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ Settings")
    use_hybrid = st.toggle("Use Hybrid Search", value=False)
    use_reranking = st.toggle("Use Re-ranking", value=False)
    
    st.header("📂 Data Management")
    
    uploaded_files = st.file_uploader(
        "Upload Documents", 
        accept_multiple_files=True, 
        type=["pdf", "docx", "txt", "md"]
    )
    
    if uploaded_files:
        if st.button("Upload to Backend"):
            with st.spinner("Uploading files..."):
                files_payload = [
                    ("files", (f.name, f.getvalue(), f.type)) for f in uploaded_files
                ]
                data = safe_api_request("POST", "/upload", files=files_payload)
                if data:
                    st.success(data["message"])

    documents = safe_api_request("GET", "/files")
    if documents:
        for document in documents.get("files", []):
            name = document["name"]
            st.caption(f"{name} · {document['chunks']} chunks")
            if st.button(f"Delete {name}", key=f"delete_{name}"):
                if safe_api_request("DELETE", f"/file/{quote(name, safe='')}"):
                    st.rerun()
            
    st.divider()
    
    if st.button("🔄 Build/Rebuild Index"):
        with st.spinner("Rebuilding index on backend..."):
            data = safe_api_request("POST", "/index")
            if data:
                st.success("Index rebuilt successfully!")

# --- Chat Interface ---
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant" and "sources" in message and message["sources"]:
            render_sources(message["sources"])

# --- Chat Input ---
if prompt := st.chat_input("What would you like to know?", max_chars=1000):
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)
        
    with st.chat_message("assistant"):
        with st.spinner("Agent is thinking..."):
            history = [{"role": m["role"], "content": m["content"][:3000]} for m in st.session_state.messages[:-1][-6:]]
            
            data = safe_api_request("POST", "/query", json={
                "query": prompt,
                "history": history,
                "use_hybrid": use_hybrid,
                "use_reranking": use_reranking
            })
            
            if data:
                answer = data.get("answer", "")
                sources = data.get("sources", [])
                
                st.markdown(answer)
                if sources:
                    render_sources(sources)
                            
                st.session_state.messages.append({
                    "role": "assistant", 
                    "content": answer,
                    "sources": sources
                })
                st.session_state.messages = st.session_state.messages[-60:]
