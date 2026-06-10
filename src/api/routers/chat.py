"""
Chat endpoint — main RAG query handler.
POST /chat — accepts question + session_id, returns AI response.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from loguru import logger

from src.database.connection import get_db
from src.api.schemas.chat import ChatRequest, ChatResponse
from src.rag.rag_pipeline import RAGPipeline
from src.memory.context_manager import ContextManager
from src.memory.long_term import LongTermMemory

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
) -> ChatResponse:
    """
    Process a user question through the RAG pipeline.

    - If session_id is provided, loads existing session context.
    - If no session_id, creates a new session automatically.
    - Conversation history and context persist to PostgreSQL.
    """
    # Guard against empty / whitespace-only questions
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    lt_memory = LongTermMemory(db)

    # Get or create session
    session_id = request.session_id

    if not session_id or session_id == "unknown":
        session = lt_memory.create_session()
        session_id = str(session.id)

    # Load session context and history
    context_mgr = ContextManager(db, session_id=session_id)
    context = context_mgr.get_context()
    history = context_mgr.get_history()

    logger.info(f"Chat | session={session_id[:8]}... | query='{request.question[:80]}'")

    try:
        pipeline = RAGPipeline(db)
        result = pipeline.query(
            question=request.question,
            conversation_history=history,
            session_context=context,
            session_id=session_id,
        )
    except Exception as e:
        logger.error(f"RAG pipeline error: {e}")
        raise HTTPException(status_code=500, detail=f"RAG pipeline failed: {str(e)}")

    # Save this turn + update context from entities
    context_mgr.add_turn(request.question, result["answer"])
    context_mgr.update_context_from_entities(result.get("entities", {}))

    return ChatResponse(
        answer=result["answer"],
        session_id=session_id,
        sources=result.get("sources", []),
        entities=result.get("entities", {}),
        retrieval_type=result.get("retrieval_type", "unknown"),
        latency_ms=result.get("latency_ms", 0.0),
        tokens_used=result.get("tokens_used", {}),
    )