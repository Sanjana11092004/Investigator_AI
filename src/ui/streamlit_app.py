"""
Investigator AI — Streamlit chat UI.

Native chat components render the assistant's markdown (headings, bold,
lists, tables). Each answer shows its retrieval strategy, latency, token
usage, evidence sources, and extracted clinical entities.

Typography: Nunito for headings, Inter for body.
"""
import os
from typing import Optional

import requests
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")

USER_AVATAR = "🧑‍⚕️"
BOT_AVATAR = "🔬"

EXAMPLE_PROMPTS = [
    "Show all serious adverse events",
    "Which patients had liver toxicity?",
    "Show only patients above age 60",
    "Show the demographics for patient SUBJ-0007",
    "Describe the hepatotoxicity case narrative from the patient report",
    "How many patients are in the database?",
]

st.set_page_config(
    page_title="Investigator AI",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Styling ──────────────────────────────────────────────────────────────────
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Nunito:wght@600;700;800&display=swap');

html, body, [class*="css"], .stMarkdown, input, textarea, button, .stTextInput {
    font-family: 'Inter', -apple-system, system-ui, sans-serif !important;
}
h1, h2, h3, h4 { font-family: 'Nunito', sans-serif !important; letter-spacing: -.3px; }

#MainMenu, header, footer {visibility: hidden;}
.stApp { background: #f5f7fb; }
.block-container { max-width: 1340px; padding-top: 1.3rem; padding-bottom: 7.5rem;
                   padding-left: 2.2rem; padding-right: 2.2rem; font-size: 15.5px; }

/* ── App header (light) ─────────────────────────────────── */
.app-header {
    background: linear-gradient(135deg, #eaf2ff 0%, #f3f8ff 55%, #ffffff 100%);
    border: 1px solid #dbe6fb;
    border-radius: 18px;
    padding: 22px 28px;
    margin-bottom: 18px;
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 6px 22px rgba(37,99,235,.08);
}
.app-header .left { display:flex; align-items:center; gap:16px; }
.app-header .logo {
    width:54px; height:54px; border-radius:15px; font-size:28px;
    display:flex; align-items:center; justify-content:center;
    background: linear-gradient(135deg,#2563eb,#0ea5e9); color:#fff;
    box-shadow: 0 6px 16px rgba(37,99,235,.32);
}
.app-header h1 { font-size:27px; font-weight:800; margin:0; color:#0f172a; }
.app-header p  { margin:5px 0 0; color:#475569; font-size:14.5px; }
.hdr-badge {
    font-size:12.5px; font-weight:700; padding:8px 15px; border-radius:999px;
    background:#eaf1ff; color:#1d4ed8; border:1px solid #cfe0ff; white-space:nowrap;
}

/* ── Metrics strip ──────────────────────────────────────── */
.metrics { display:flex; gap:12px; margin: 0 0 22px; flex-wrap:wrap; }
.metric {
    flex:1; min-width:130px; background:#fff; border:1px solid #e7edf5;
    border-radius:14px; padding:15px 18px; box-shadow:0 1px 3px rgba(16,24,40,.05);
}
.metric .m-label { font-size:11.5px; font-weight:700; letter-spacing:.06em;
                   text-transform:uppercase; color:#64748b; }
.metric .m-value { font-family:'Nunito',sans-serif; font-size:27px; font-weight:800;
                   color:#0f172a; margin-top:3px; }
.metric .m-bar { height:3.5px; width:30px; border-radius:3px; margin-top:9px; }

/* ── Chips under answers ────────────────────────────────── */
.chip {
    display:inline-block; padding:3px 12px; border-radius:999px;
    font-size:12px; font-weight:600; margin:3px 6px 3px 0; line-height:1.7;
}
.chip-sql    { background:#eff4ff; color:#1d4ed8; border:1px solid #cfe0ff; }
.chip-vector { background:#ecfdf3; color:#15803d; border:1px solid #c4ead2; }
.chip-hybrid { background:#fffaeb; color:#b45309; border:1px solid #fce7a6; }
.chip-error  { background:#fef2f2; color:#b91c1c; border:1px solid #fbd2d2; }
.chip-meta   { background:#f3f6fb; color:#475569; border:1px solid #e3e9f2; }
.chip-src    { background:#f5f8ff; color:#2563eb; border:1px solid #d8e4fb; }
.chip-ent    { background:#f8f6ff; color:#6d28d9; border:1px solid #e6dffb; }

/* ── Chat ───────────────────────────────────────────────── */
[data-testid="stChatMessage"] { background:transparent; padding:2px 0; }
[data-testid="stChatMessageContent"] { font-size:16px; line-height:1.62; color:#1e293b; }
[data-testid="stChatMessageContent"] p { margin-bottom:.55rem; }
[data-testid="stChatMessageContent"] li { margin-bottom:.2rem; }

/* ── Tables (clinical report style, Times New Roman) ────── */
.stMarkdown table, [data-testid="stChatMessageContent"] table {
    font-family: 'Times New Roman', Times, serif !important;
    border-collapse: separate; border-spacing: 0; width: 100%; margin: 14px 0;
    font-size: 14.5px; border: 1px solid #d8e2ee; border-radius: 12px; overflow: hidden;
    box-shadow: 0 2px 8px rgba(16,24,40,.06);
}
.stMarkdown table thead th, [data-testid="stChatMessageContent"] table thead th {
    background: linear-gradient(180deg,#1e40af,#1d4ed8); color: #fff;
    font-family: 'Times New Roman', Times, serif !important; font-weight: 700;
    text-align: left; padding: 11px 14px; font-size: 14px; border: none; white-space: nowrap;
}
.stMarkdown table tbody td, [data-testid="stChatMessageContent"] table tbody td {
    padding: 10px 14px; border-top: 1px solid #eef2f8; color: #1f2937; vertical-align: top;
}
.stMarkdown table tbody tr:nth-child(even),
[data-testid="stChatMessageContent"] table tbody tr:nth-child(even) { background: #f6f9ff; }
.stMarkdown table tbody tr:hover,
[data-testid="stChatMessageContent"] table tbody tr:hover { background: #e7f0ff; transition: background .12s ease; }
.stMarkdown table tbody td:first-child,
[data-testid="stChatMessageContent"] table tbody td:first-child { font-weight: 700; color: #1e3a8a; white-space: nowrap; }

/* metric hover lift */
.metric { transition: transform .12s ease, box-shadow .12s ease; }
.metric:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(16,24,40,.10); }

/* ── Sidebar ────────────────────────────────────────────── */
section[data-testid="stSidebar"] { background:#fff; border-right:1px solid #e7edf5; }
section[data-testid="stSidebar"] .stButton button {
    border-radius:10px; border:1px solid #e6ebf3; text-align:left;
    font-size:13.5px; background:#fff; color:#334155; font-weight:500;
}
section[data-testid="stSidebar"] .stButton button:hover { border-color:#2563eb; color:#1d4ed8; background:#f7faff; }
.brand { display:flex; align-items:center; gap:11px; margin-bottom:3px; }
.brand .logo { font-size:25px; }
.brand .name { font-family:'Nunito',sans-serif; font-size:19px; font-weight:800; color:#0f172a; }
.dot { height:9px; width:9px; border-radius:50%; display:inline-block; margin-right:7px; }
.dot-on  { background:#22c55e; box-shadow:0 0 0 3px rgba(34,197,94,.16); }
.dot-off { background:#ef4444; box-shadow:0 0 0 3px rgba(239,68,68,.16); }
.side-h { font-size:11.5px; font-weight:700; letter-spacing:.06em; text-transform:uppercase;
          color:#94a3b8; margin:8px 0 5px; }

/* welcome + footer */
.welcome-h { font-family:'Nunito',sans-serif; color:#0f172a; font-weight:800;
             font-size:23px; margin-bottom:5px; }
.disclaimer { text-align:center; color:#94a3b8; font-size:12.5px; margin-top:28px;
              padding-top:14px; border-top:1px solid #e7edf5; }
</style>
""",
    unsafe_allow_html=True,
)


# ─── Session state ──────────────────────────────────────────────────────────
def init_state():
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("session_id", None)
    st.session_state.setdefault("current_context", {})
    st.session_state.setdefault("pending_prompt", None)


# ─── API helpers ──────────────────────────────────────────────────────────────
def api_health() -> bool:
    try:
        return requests.get(f"{API_BASE}/health", timeout=4).status_code == 200
    except Exception:
        return False


def api_stats() -> dict:
    try:
        return requests.get(f"{API_BASE}/stats", timeout=6).json()
    except Exception:
        return {}


def api_chat(question: str, session_id: Optional[str]) -> dict:
    try:
        resp = requests.post(
            f"{API_BASE}/chat",
            json={"question": question, "session_id": session_id},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return _error_result(
            "⚠️ Cannot reach the backend. Start it with "
            "`python -m uvicorn src.api.main:app --port 8000`.",
            session_id,
        )
    except Exception as e:
        return _error_result(f"⚠️ Error: {e}", session_id)


def _error_result(msg: str, session_id):
    return {
        "answer": msg, "session_id": session_id, "sources": [],
        "entities": {}, "retrieval_type": "error", "latency_ms": 0, "tokens_used": {},
    }


def api_create_session(name: str = None) -> Optional[str]:
    try:
        r = requests.post(f"{API_BASE}/sessions", json={"name": name}, timeout=10)
        r.raise_for_status()
        return r.json().get("id")
    except Exception:
        return None


def api_upload_file(file_bytes: bytes, filename: str, session_id: Optional[str] = None) -> dict:
    try:
        data = {"session_id": session_id} if session_id else {}
        resp = requests.post(
            f"{API_BASE}/ingest/upload",
            files={"file": (filename, file_bytes)},
            data=data,
            timeout=180,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"success": False, "message": str(e), "records": 0, "file_name": filename}


def api_list_sessions() -> list:
    try:
        return requests.get(f"{API_BASE}/sessions", timeout=10).json()
    except Exception:
        return []


def api_list_documents() -> list:
    try:
        return requests.get(f"{API_BASE}/ingest/documents", timeout=10).json()
    except Exception:
        return []


def api_get_session(session_id: str) -> dict:
    try:
        return requests.get(f"{API_BASE}/sessions/{session_id}", timeout=10).json()
    except Exception:
        return {}


def model_label(model_id: str) -> str:
    if not model_id:
        return "Groq Llama"
    m = model_id.lower()
    if "70b" in m:
        return "Groq · Llama 3.3 70B"
    if "8b" in m:
        return "Groq · Llama 3.1 8B"
    return f"Groq · {model_id}"


# ─── Rendering helpers ────────────────────────────────────────────────────────
def render_metrics(stats: dict):
    if not stats:
        return
    cards = [
        ("Patients", stats.get("patients", 0), "#2563eb"),
        ("Adverse Events", stats.get("adverse_events", 0), "#dc2626"),
        ("Lab Results", stats.get("lab_results", 0), "#0891b2"),
        ("Medications", stats.get("medications", 0), "#7c3aed"),
        ("Studies", stats.get("studies", 0), "#16a34a"),
        ("Documents", stats.get("documents", 0), "#d97706"),
    ]
    html = "<div class='metrics'>"
    for label, value, color in cards:
        html += (
            f"<div class='metric'><div class='m-label'>{label}</div>"
            f"<div class='m-value'>{value:,}</div>"
            f"<div class='m-bar' style='background:{color}'></div></div>"
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_answer_extras(msg: dict):
    """Render chips (strategy/latency/tokens), sources, and entities for an answer."""
    strategy = msg.get("retrieval_type", "")
    latency = msg.get("latency_ms")
    tokens = (msg.get("tokens_used") or {}).get("total")
    sources = msg.get("sources") or []
    entities = {k: v for k, v in (msg.get("entities") or {}).items() if v}

    chips = ""
    if strategy:
        cls = {"sql": "chip-sql", "vector": "chip-vector",
               "hybrid": "chip-hybrid", "error": "chip-error"}.get(strategy, "chip-meta")
        chips += f'<span class="chip {cls}">🧭 {strategy.upper()}</span>'
    if latency:
        chips += f'<span class="chip chip-meta">⚡ {latency} ms</span>'
    if tokens:
        chips += f'<span class="chip chip-meta">🔢 {tokens} tokens</span>'
    for s in sources:
        chips += f'<span class="chip chip-src">📊 {s}</span>'
    if chips:
        st.markdown(chips, unsafe_allow_html=True)

    if entities:
        with st.expander("🔎 Extracted entities"):
            ent_html = ""
            for cat, vals in entities.items():
                label = cat.replace("_", " ").title()
                tags = " ".join(f'<span class="chip chip-ent">{v}</span>' for v in vals[:12])
                ent_html += f"<div style='margin-bottom:7px;font-size:14px'><b>{label}:</b> {tags}</div>"
            st.markdown(ent_html, unsafe_allow_html=True)


def render_history():
    for msg in st.session_state.messages:
        avatar = USER_AVATAR if msg["role"] == "user" else BOT_AVATAR
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])
            if msg["role"] == "assistant":
                render_answer_extras(msg)


def process_prompt(question: str):
    """Echo the user turn, call the API with a spinner, store + render the answer."""
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(question)
    st.session_state.messages.append({"role": "user", "content": question})

    with st.chat_message("assistant", avatar=BOT_AVATAR):
        with st.spinner("Investigating the clinical data…"):
            result = api_chat(question, st.session_state.session_id)
        st.markdown(result.get("answer", "No response received."))
        assistant_msg = {
            "role": "assistant",
            "content": result.get("answer", ""),
            "sources": result.get("sources", []),
            "retrieval_type": result.get("retrieval_type", ""),
            "latency_ms": result.get("latency_ms"),
            "tokens_used": result.get("tokens_used", {}),
            "entities": result.get("entities", {}),
        }
        render_answer_extras(assistant_msg)

    st.session_state.messages.append(assistant_msg)

    sid = result.get("session_id")
    if sid and sid != "unknown":
        st.session_state.session_id = sid
    ents = result.get("entities", {})
    if ents.get("studies"):
        st.session_state.current_context["active_study_id"] = ents["studies"][0]
    if ents.get("patients") and len(ents["patients"]) == 1:
        st.session_state.current_context["active_patient_id"] = ents["patients"][0]
    st.rerun()


# ─── Sidebar ──────────────────────────────────────────────────────────────────
def render_sidebar(backend_ok: bool):
    with st.sidebar:
        st.markdown(
            '<div class="brand"><span class="logo">🔬</span>'
            '<span class="name">Investigator AI</span></div>',
            unsafe_allow_html=True,
        )
        dot = "dot-on" if backend_ok else "dot-off"
        status = "Backend connected" if backend_ok else "Backend offline"
        st.markdown(
            f'<div style="font-size:13px;color:#64748b;margin-bottom:8px">'
            f'<span class="dot {dot}"></span>{status}</div>',
            unsafe_allow_html=True,
        )
        st.divider()

        if st.button("➕  New Investigation", use_container_width=True):
            st.session_state.session_id = None
            st.session_state.messages = []
            st.session_state.current_context = {}
            st.rerun()

        st.markdown('<div class="side-h">Past investigations</div>', unsafe_allow_html=True)
        sessions = api_list_sessions()
        if sessions:
            for s in sessions[:10]:
                icon = "🟢" if s.get("status") == "active" else "⚪"
                label = f"{icon} {s['name'][:28]}"
                meta = f"{s.get('turn_count', 0)} turns"
                if s.get("active_study_id"):
                    meta += f" · {s['active_study_id']}"
                if st.button(label, help=meta, key=f"s_{s['id']}", use_container_width=True):
                    _load_session(s["id"])
        else:
            st.caption("No past sessions yet.")

        st.divider()

        st.markdown('<div class="side-h">Upload data</div>', unsafe_allow_html=True)
        up = st.file_uploader(
            "CSV / JSON / PDF", type=["pdf", "csv", "json"],
            label_visibility="collapsed",
            help="SDTM CSV (DM/AE/LB/CM/MH), ClinicalTrials JSON, or narrative PDF",
        )
        if up and st.button("⬆️  Ingest file", use_container_width=True):
            # Tie the upload to this investigation so it's scoped to this session
            if not st.session_state.session_id:
                st.session_state.session_id = api_create_session("Investigation")
            with st.spinner(f"Ingesting {up.name}…"):
                res = api_upload_file(up.getvalue(), up.name, st.session_state.session_id)
            if res.get("success"):
                if res.get("records", 0) == 0:
                    st.info(f"ℹ️ {res.get('message', 'Already ingested.')}")
                else:
                    st.success(f"✅ {res['records']} records from {up.name}")
                    # Surface any ingestor-specific extras generically (e.g. a PDF's
                    # structured_patients). New file types appear here automatically.
                    details = res.get("details") or {}
                    if details.get("structured_patients"):
                        st.caption(f"🧬 {details['structured_patients']} patients structured for exact lookups")
                    for k, v in details.items():
                        if k == "structured_patients" or v in (None, "", [], {}):
                            continue
                        st.caption(f"• {k.replace('_', ' ')}: {v}")
            else:
                st.error(f"❌ {res.get('message', 'Ingestion failed')}")

        with st.expander("📂 Ingested documents"):
            docs = api_list_documents()
            if docs:
                for d in docs[:20]:
                    icon = {"narrative_pdf": "📄", "sdtm": "📊",
                            "clinical_trials_json": "🧪"}.get(d["file_type"], "📁")
                    st.caption(f"{icon} **{d['file_name']}** — {d['record_count']} · {d['status']}")
            else:
                st.caption("None yet.")

        ctx = st.session_state.current_context
        if ctx.get("active_study_id") or ctx.get("active_patient_id"):
            st.divider()
            st.markdown('<div class="side-h">Active context</div>', unsafe_allow_html=True)
            if ctx.get("active_study_id"):
                st.caption(f"**Study:** {ctx['active_study_id']}")
            if ctx.get("active_patient_id"):
                st.caption(f"**Patient:** {ctx['active_patient_id']}")


def _load_session(session_id: str):
    st.session_state.session_id = session_id
    full = api_get_session(session_id)
    history = full.get("conversation_history", []) or []
    msgs = []
    for h in history:
        msgs.append({
            "role": h.get("role", "user"),
            "content": h.get("content", ""),
            "sources": [], "entities": {}, "retrieval_type": "", "tokens_used": {},
        })
    st.session_state.messages = msgs
    st.session_state.current_context = {
        "active_study_id": full.get("active_study_id"),
        "active_patient_id": full.get("active_patient_id"),
    }
    st.rerun()


# ─── Welcome screen ───────────────────────────────────────────────────────────
def render_welcome():
    st.markdown(
        "<div style='text-align:center;color:#64748b;padding:8px 0 16px'>"
        "<div class='welcome-h'>Start a clinical investigation</div>"
        "<p style='font-size:15px'>Ask in plain English — the assistant remembers the study "
        "&amp; patient context across follow-up questions.</p></div>",
        unsafe_allow_html=True,
    )
    st.markdown('<div class="side-h" style="color:#94a3b8">Suggested questions</div>',
                unsafe_allow_html=True)
    cols = st.columns(2)
    for i, ex in enumerate(EXAMPLE_PROMPTS):
        if cols[i % 2].button(ex, key=f"ex_{i}", use_container_width=True):
            st.session_state.pending_prompt = ex
            st.rerun()


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    init_state()
    backend_ok = api_health()
    stats = api_stats() if backend_ok else {}
    render_sidebar(backend_ok)

    badge = model_label(stats.get("model", "")) if stats else "Hybrid RAG"
    st.markdown(
        "<div class='app-header'>"
        "<div class='left'><div class='logo'>🔬</div>"
        "<div><h1>Investigator AI Assistant</h1>"
        "<p>Conversational RAG over clinical-trial &amp; pharmacovigilance data, with memory</p></div></div>"
        f"<div class='hdr-badge'>Hybrid RAG · {badge}</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    if not backend_ok:
        st.error(
            f"Backend API is not reachable at `{API_BASE}`. Start it with "
            "`python -m uvicorn src.api.main:app --port 8000` and refresh."
        )
    else:
        render_metrics(stats)

    if not st.session_state.messages:
        render_welcome()
    else:
        render_history()

    typed = st.chat_input("Ask about adverse events, patients, labs, studies…")
    pending = st.session_state.pending_prompt
    st.session_state.pending_prompt = None
    question = typed or pending
    if question and question.strip():
        process_prompt(question.strip())

    st.markdown(
        "<div class='disclaimer'>⚕️ For research &amp; demonstration use only — "
        "not for clinical decision-making. Answers are grounded in the ingested study data.</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
