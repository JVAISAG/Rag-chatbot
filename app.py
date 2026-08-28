import streamlit as st
import os
from src.pipeline import RAGPipeline

st.set_page_config(page_title="Personal RAG Chatbot", layout="wide")

@st.cache_resource
def get_pipeline():
    return RAGPipeline(llm_model="llama3.2")

pipeline = get_pipeline()

st.title("Personal RAG Chatbot")

# Sidebar for settings and indexing
with st.sidebar:
    st.header("Settings")
    use_hybrid = st.toggle("Use Hybrid Search (BM25 + Dense)", value=False)
    use_reranking = st.toggle("Use Cross-Encoder Re-ranking", value=False)
    
    st.header("Data Management")
    
    uploaded_files = st.file_uploader(
        "Upload Documents", 
        accept_multiple_files=True, 
        type=["pdf", "docx", "txt", "md"]
    )
    
    if uploaded_files:
        if st.button("Save Uploaded Files"):
            data_dir = os.path.join(os.path.dirname(__file__), "data")
            os.makedirs(data_dir, exist_ok=True)
            saved_count = 0
            for uploaded_file in uploaded_files:
                file_path = os.path.join(data_dir, uploaded_file.name)
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                saved_count += 1
            st.success(f"Successfully saved {saved_count} file(s) to data folder. Click 'Build/Rebuild Index' below.")
            
    st.divider()
    
    if st.button("Remove All Files"):
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        if os.path.exists(data_dir):
            removed_count = 0
            for file_name in os.listdir(data_dir):
                file_path = os.path.join(data_dir, file_name)
                if os.path.isfile(file_path):
                    try:
                        os.remove(file_path)
                        removed_count += 1
                    except Exception as e:
                        st.error(f"Failed to remove {file_name}: {e}")
            st.success(f"Removed {removed_count} file(s) from the data folder.")
        else:
            st.info("Data folder is empty.")

    if st.button("Build/Rebuild Index"):
        with st.spinner("Building index..."):
            success = pipeline.build_index()
            if success:
                st.success("Index built successfully!")
            else:
                st.error("Failed to build index. Check data folder.")

# Chat Interface
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        
        # Display sources if available
        if message["role"] == "assistant" and "sources" in message and message["sources"]:
            with st.expander("View Sources"):
                for i, source in enumerate(message["sources"], start=1):
                    meta = source.get("metadata", {})
                    src_name = meta.get("source", "Unknown")
                    st.markdown(f"**[{i}] Source: {src_name}**")
                    st.text(source["text"])

# Chat Input
if prompt := st.chat_input("Ask a question about your documents..."):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    with st.chat_message("user"):
        st.markdown(prompt)
        
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            # We pass the history excluding the current prompt
            history = st.session_state.messages[:-1]
            answer, sources = pipeline.query(
                user_query=prompt,
                history=history,
                use_hybrid=use_hybrid,
                use_reranking=use_reranking
            )
            
            st.markdown(answer)
            
            if sources:
                with st.expander("View Sources"):
                    for i, source in enumerate(sources, start=1):
                        # Handle new citation format or fallback to chunk format
                        if "text_snippet" in source:
                            src_name = source.get("source", "Unknown")
                            citation_mark = source.get("citation", f"[{i}]")
                            st.markdown(f"**{citation_mark} Source: {src_name}**")
                            st.text(source.get("text_snippet", ""))
                        else:
                            meta = source.get("metadata", {})
                            src_name = meta.get("source", "Unknown")
                            st.markdown(f"**[{i}] Source: {src_name}**")
                            st.text(source.get("text", ""))
                        
    # Add assistant message to chat history
    st.session_state.messages.append({
        "role": "assistant", 
        "content": answer,
        "sources": sources
    })
