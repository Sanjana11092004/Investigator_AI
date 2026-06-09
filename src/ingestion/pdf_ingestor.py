"""
Medical Narrative PDF Ingestor.
Extracts text from PDFs, chunks them, embeds, and stores in ChromaDB.
Also runs entity extraction and stores in PostgreSQL.
"""
import os
from pathlib import Path
from typing import Dict, Any, List

import fitz  # PyMuPDF
from sqlalchemy.orm import Session
from loguru import logger

from src.ingestion.base_ingestor import BaseIngestor
from src.ingestion.deduplication import (
    compute_file_hash,
    is_already_ingested,
    register_document,
)
from src.embeddings.chunker import chunk_text
from src.embeddings.embedder import get_embedder
from src.vector_store.chroma_store import get_vector_store


class PDFIngestor(BaseIngestor):
    """
    Ingests medical narrative PDF files into ChromaDB vector store.
    Performs text extraction, chunking, embedding, and indexing.
    """

    def can_handle(self, file_path: str) -> bool:
        return file_path.lower().endswith(".pdf")

    def ingest(self, file_path: str, **kwargs) -> Dict[str, Any]:
        file_hash = compute_file_hash(file_path)

        if is_already_ingested(self.db, file_hash):
            return {"success": True, "records": 0, "message": "Already ingested. Skipped."}

        try:
            text_pages = self._extract_text(file_path)
        except Exception as e:
            logger.error(f"PDF extraction failed for {file_path}: {e}")
            register_document(
                self.db, Path(file_path).name, file_path, file_hash,
                "narrative_pdf", os.path.getsize(file_path),
                status="failed", error_message=str(e)
            )
            return {"success": False, "records": 0, "message": str(e)}

        file_name = Path(kwargs.get("original_filename") or file_path).name
        all_chunks = []
        all_metadatas = []
        all_ids = []

        for page_num, page_text in enumerate(text_pages, start=1):
            if not page_text.strip():
                continue
            chunks = chunk_text(page_text)
            for chunk_idx, chunk in enumerate(chunks):
                chunk_id = f"{file_hash}_{page_num}_{chunk_idx}"
                all_chunks.append(chunk)
                all_metadatas.append({
                    "source": file_name,
                    "file_hash": file_hash,
                    "page": page_num,
                    "chunk_index": chunk_idx,
                    "doc_type": "narrative_pdf",
                })
                all_ids.append(chunk_id)

        if not all_chunks:
            logger.warning(f"No text extracted from {file_name}")
            return {"success": False, "records": 0, "message": "No text extracted"}

        # Store in ChromaDB
        vector_store = get_vector_store()
        embedder = get_embedder()
        embeddings = embedder.embed_documents(all_chunks)

        vector_store.add(
            documents=all_chunks,
            embeddings=embeddings,
            metadatas=all_metadatas,
            ids=all_ids,
        )

        register_document(
            self.db,
            file_name,
            file_path,
            file_hash,
            "narrative_pdf",
            os.path.getsize(file_path),
            record_count=len(all_chunks),
        )

        logger.info(f"PDF ingestor: {len(all_chunks)} chunks from {file_name} ({len(text_pages)} pages)")
        return {
            "success": True,
            "records": len(all_chunks),
            "message": f"Indexed {len(all_chunks)} chunks from {len(text_pages)} pages",
        }

    def _extract_text(self, file_path: str) -> List[str]:
        """
        Extract text from all pages of a PDF.
        
        Returns:
            List of page texts.
        """
        doc = fitz.open(file_path)
        pages = []
        for page in doc:
            text = page.get_text("text")
            pages.append(text)
        doc.close()
        return pages