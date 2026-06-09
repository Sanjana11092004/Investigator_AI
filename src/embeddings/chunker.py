"""
Document chunking strategies for RAG.
Uses a sliding window approach with configurable overlap.
"""
from typing import List
from src.config.settings import settings


def chunk_text(
    text: str,
    chunk_size: int = None,
    chunk_overlap: int = None,
) -> List[str]:
    """
    Split text into overlapping chunks for embedding.
    
    Uses word-boundary chunking to avoid splitting mid-word.
    Respects sentence boundaries when possible.
    
    Args:
        text: Full document text.
        chunk_size: Target chunk size in characters. Defaults to settings value.
        chunk_overlap: Overlap in characters. Defaults to settings value.
    
    Returns:
        List of text chunks.
    """
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    if not text or not text.strip():
        return []

    text = text.strip()

    # Split into sentences first (rough heuristic)
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        # If adding this sentence would exceed chunk_size
        if len(current_chunk) + len(sentence) > chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            # Start new chunk with overlap from previous
            overlap_start = max(0, len(current_chunk) - chunk_overlap)
            current_chunk = current_chunk[overlap_start:] + " " + sentence
        else:
            current_chunk += " " + sentence if current_chunk else sentence

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # Filter out very short chunks (likely noise)
    return [c for c in chunks if len(c) > 50]