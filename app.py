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
                        meta = source.get("metadata", {})
                        src_name = meta.get("source", "Unknown")
                        st.markdown(f"**[{i}] Source: {src_name}**")
                        st.text(source["text"])
                        
    # Add assistant message to chat history
    st.session_state.messages.append({
        "role": "assistant", 
        "content": answer,
        "sources": sources
    })
