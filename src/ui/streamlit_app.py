"""
Streamlit Chat UI — ChatGPT-style interface for the Investigator AI.
Minimal, clean, functional.
"""
import streamlit as st
import requests
import json
from typing import Optional
import os

# --- Config ---
API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Investigator AI",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS for ChatGPT-like appearance ---
st.markdown("""
<style>

/* Hide Streamlit Elements */
#MainMenu {visibility:hidden;}
footer {visibility:hidden;}
header {visibility:hidden;}

/* App Background */
.stApp{
    background:#F8FAFC;
}

/* Main Width */
.block-container{
    max-width:1200px;
    padding-top:1rem;
}

/* User Message */
.user-message{
    background:#2563EB;
    color:white;
    padding:14px 18px;
    border-radius:16px;
    margin-left:auto;
    width:fit-content;
    max-width:75%;
    box-shadow:0 2px 8px rgba(0,0,0,.08);
}

/* Assistant Message */
.assistant-message{
    background:white;
    color:#1E293B;
    padding:18px;
    border-radius:16px;
    border:1px solid #E2E8F0;
    max-width:90%;
    box-shadow:0 2px 8px rgba(0,0,0,.04);
}

/* Metadata */
.meta-info{
    color:#64748B;
    font-size:12px;
    margin-top:8px;
}

/* Source Tags */
.source-badge{
    display:inline-block;
    background:#EFF6FF;
    color:#2563EB;
    border:1px solid #BFDBFE;
    padding:4px 10px;
    border-radius:20px;
    margin:2px;
    font-size:12px;
}

/* Sidebar */
section[data-testid="stSidebar"]{
    background:#FFFFFF;
    border-right:1px solid #E2E8F0;
}

/* Buttons */
.stButton button{
    border-radius:10px;
    border:1px solid #CBD5E1;
}

/* Inputs */
.stTextInput input{
    border-radius:12px;
}

</style>
""", unsafe_allow_html=True)


# ─── Session State Initialization ───────────────────────────────────────────

def init_state():
    """Initialize all Streamlit session state variables."""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = None
    if "sessions_list" not in st.session_state:
        st.session_state.sessions_list = []
    if "current_context" not in st.session_state:
        st.session_state.current_context = {}


# ─── API Helpers ─────────────────────────────────────────────────────────────

def api_chat(question: str, session_id: Optional[str]) -> dict:
    """Call the /chat endpoint."""
    try:
        resp = requests.post(
            f"{API_BASE}/chat",
            json={"question": question, "session_id": session_id},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return {
            "answer": "⚠️ Cannot connect to the backend. Make sure the FastAPI server is running (`python -m src.api.main`).",
            "session_id": session_id,
            "sources": [],
            "entities": {},
            "retrieval_type": "error",
            "latency_ms": 0,
            "tokens_used": {},
        }
    except Exception as e:
        return {
            "answer": f"⚠️ Error: {str(e)}",
            "session_id": session_id,
            "sources": [],
            "entities": {},
            "retrieval_type": "error",
            "latency_ms": 0,
            "tokens_used": {},
        }


def api_upload_file(file_bytes: bytes, filename: str) -> dict:
    """Call the /ingest/upload endpoint."""
    try:
        resp = requests.post(
            f"{API_BASE}/ingest/upload",
            files={"file": (filename, file_bytes)},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"success": False, "message": str(e), "records": 0, "file_name": filename}


def api_list_sessions() -> list:
    """Fetch all sessions from backend."""
    try:
        resp = requests.get(f"{API_BASE}/sessions", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def api_list_documents() -> list:
    """Fetch all ingested documents."""
    try:
        resp = requests.get(f"{API_BASE}/ingest/documents", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def api_get_session(session_id: str) -> dict:
    """Load a specific session's full details."""
    try:
        resp = requests.get(f"{API_BASE}/sessions/{session_id}", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


# ─── Sidebar ─────────────────────────────────────────────────────────────────

def render_sidebar():
    """Render the sidebar with session management and file upload."""
    with st.sidebar:
        st.markdown("""
        <h2 style='margin-bottom:0'>
        Investigator AI
        </h2>
        """, unsafe_allow_html=True)

        st.caption("Clinical Investigation Platform")
        st.divider()

        # --- New Session ---
        if st.button("➕ New Investigation", use_container_width=True):
            st.session_state.session_id = None
            st.session_state.messages = []
            st.session_state.current_context = {}
            st.rerun()

        st.divider()

        # --- Past Sessions ---
        st.subheader("📋 Past Sessions")
        sessions = api_list_sessions()
        if sessions:
            for s in sessions[:10]:
                label = f"{'🟢' if s['status'] == 'active' else '⚪'} {s['name'][:30]}"
                sub = f"{s['turn_count']} turns"
                if s.get("active_study_id"):
                    sub += f" · Study: {s['active_study_id']}"
                if st.button(label, help=sub, key=f"sess_{s['id']}", use_container_width=True):
                    st.session_state.session_id = s["id"]
                    # Load history from backend
                    full = api_get_session(s["id"])
                    history = full.get("conversation_history", [])
                    # Convert to display format
                    st.session_state.messages = []
                    for i in range(0, len(history) - 1, 2):
                        if i < len(history):
                            st.session_state.messages.append({
                                "role": "user",
                                "content": history[i].get("content", ""),
                            })
                        if i + 1 < len(history):
                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": history[i + 1].get("content", ""),
                                "sources": [],
                                "meta": {},
                            })
                    st.rerun()
        else:
            st.caption("No sessions yet. Start by asking a question.")

        st.divider()

        # --- File Upload ---
        st.subheader("📁 Upload Data")
        uploaded = st.file_uploader(
            "Upload clinical data",
            type=["pdf", "csv", "json"],
            help="Supported: ClinicalTrials JSON, SDTM CSV (DM/LB/AE/CM/MH), PDF narratives",
        )
        if uploaded:
            if st.button("⬆️ Ingest File", use_container_width=True):
                with st.spinner(f"Ingesting {uploaded.name}..."):
                    result = api_upload_file(uploaded.getvalue(), uploaded.name)
                if result.get("success"):
                    if result.get("records", 0) == 0:
                        st.info(f"ℹ️ {result.get('message', 'Already ingested.')}")
                    else:
                        st.success(f"✅ {result['records']} records ingested from {uploaded.name}")
                else:
                    st.error(f"❌ {result.get('message', 'Ingestion failed')}")

        st.divider()

        # --- Ingested Documents ---
        with st.expander("📂 Ingested Documents"):
            docs = api_list_documents()
            if docs:
                for d in docs[:20]:
                    icon = {"narrative_pdf": "📄", "sdtm": "📊", "clinical_trials_json": "🧪"}.get(
                        d["file_type"], "📁"
                    )
                    st.caption(
                        f"{icon} **{d['file_name']}**  \n"
                        f"{d['record_count']} records · {d['file_type']} · {d['status']}"
                    )
            else:
                st.caption("No documents ingested yet.")

        # --- Current Context ---
        if st.session_state.session_id:
            st.divider()
            with st.expander("🧭 Active Context"):
                ctx = st.session_state.current_context
                if ctx.get("active_study_id"):
                    st.caption(f"**Study:** {ctx['active_study_id']}")
                if ctx.get("active_patient_id"):
                    st.caption(f"**Patient:** {ctx['active_patient_id']}")
                extra = ctx.get("investigation_context", {})
                for k, v in extra.items():
                    if v:
                        st.caption(f"**{k}:** {v}")


# ─── Main Chat Area ───────────────────────────────────────────────────────────

def render_chat():
    """Render the main chat interface."""
    # Header
    col1, col2 = st.columns([6, 1])
    with col1:
        st.markdown("""
            <h1 style="
            font-size:34px;
            font-weight:700;
            margin-bottom:0px;
            color:#0F172A;
            ">
            Investigator AI
            </h1>
            """, unsafe_allow_html=True)

        if st.session_state.session_id:
            st.caption(
                f"Investigation Session • {st.session_state.session_id[:8]}"
            )
        else:
            st.caption("New Investigation")
    with col2:
        st.caption("")

    # Chat messages display
    chat_container = st.container()
    with chat_container:
        if not st.session_state.messages:
            st.markdown("""
            <div style="text-align:center; padding: 3rem; color: #666;">
                <h3>👋 Welcome to Investigator AI</h3>
                <p>Ask anything about your clinical study data.</p>
                <p style="font-size:0.9rem;">
                Examples:<br>
                "Show all serious adverse events"<br>
                "Which patients had liver toxicity?"<br>
                "Show patients above age 60 with grade 3 AEs"
                </p>
            </div>
            """, unsafe_allow_html=True)
        else:
            for msg in st.session_state.messages:
                render_message(msg)

    # Input area at the bottom
    st.divider()
    with st.form("chat_form", clear_on_submit=True):
        col1, col2 = st.columns([9, 1])
        with col1:
            user_input = st.text_input(
                "Ask a question...",
                placeholder="e.g. Show all serious adverse events in Study ABC-101",
                label_visibility="collapsed",
            )
        with col2:
            submitted = st.form_submit_button("Send", use_container_width=True)

    if submitted and user_input.strip():
        handle_user_message(user_input.strip())


def render_message(msg: dict):
    """Render a single chat message."""
    if msg["role"] == "user":
        st.markdown(
            f'<div class="chat-message user-message">👤 {msg["content"]}</div>',
            unsafe_allow_html=True,
        )
    else:
        content = msg["content"]
        sources = msg.get("sources", [])
        meta = msg.get("meta", {})

        # Main answer
        st.markdown(
            f'<div class="chat-message assistant-message">🔬 {content}</div>',
            unsafe_allow_html=True,
        )

        # Sources and metadata
        if sources or meta:
            source_html = ""
            for s in sources:
                source_html += f'<span class="source-badge">📊 {s}</span>'

            retrieval = meta.get("retrieval_type", "")
            latency = meta.get("latency_ms", "")
            tokens = meta.get("tokens_used", {}).get("total", "")

            meta_html = ""
            if retrieval:
                meta_html += f"Retrieval: {retrieval}"
            if latency:
                meta_html += f" · {latency}ms"
            if tokens:
                meta_html += f" · {tokens} tokens"

            st.markdown(
                f'<div class="meta-info">{source_html}<br>{meta_html}</div>',
                unsafe_allow_html=True,
            )


def handle_user_message(question: str):
    """Process a user message: add to state, call API, display response."""
    # Add user message to display
    st.session_state.messages.append({"role": "user", "content": question})

    # Call API with spinner
    with st.spinner("Investigating..."):
        result = api_chat(question, st.session_state.session_id)

    # Update session ID (in case a new one was created)
    new_session = result.get("session_id")

    if new_session and new_session != "unknown":
        st.session_state.session_id = new_session

    # Add assistant message to display
    st.session_state.messages.append({
        "role": "assistant",
        "content": result.get("answer", "No response received."),
        "sources": result.get("sources", []),
        "meta": {
            "retrieval_type": result.get("retrieval_type", ""),
            "latency_ms": result.get("latency_ms", ""),
            "tokens_used": result.get("tokens_used", {}),
        },
    })

    # Update local context display
    if result.get("entities"):
        entities = result["entities"]
        if entities.get("studies"):
            st.session_state.current_context["active_study_id"] = entities["studies"][0]
        if entities.get("patients"):
            st.session_state.current_context["active_patient_id"] = entities["patients"][0]

    st.rerun()


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def main():
    init_state()
    render_sidebar()
    render_chat()


if __name__ == "__main__":
    main()