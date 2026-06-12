"""
Medical Narrative PDF Ingestor.
Extracts text from PDFs, chunks them, and indexes them in the SQLite FTS catalog.
Also runs LLM structured extraction into the per-document JSON store.
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
from src.catalog.catalog_store import get_catalog_store
from src.config.settings import settings


class PDFIngestor(BaseIngestor):
    """
    Ingests medical narrative PDF files into the SQLite FTS catalog.
    Performs text extraction, chunking, and full-text indexing (no embeddings).
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
        # Tag chunks with the uploading session for per-session scoping; bundled /
        # bulk-ingested documents (no session) are 'global' and visible to all.
        session_id = kwargs.get("session_id") or "global"
        rows = []
        global_index = 0  # monotonic chunk index across the whole document

        for page_num, page_text in enumerate(text_pages, start=1):
            if not page_text.strip():
                continue
            for chunk in chunk_text(page_text):
                rows.append({
                    "chunk_id": f"{file_hash}_{page_num}_{global_index}",
                    "content": chunk,
                    "source": file_name,
                    "page": page_num,
                    "session_id": session_id,
                    "doc_type": "narrative_pdf",
                    "chunk_index": global_index,
                    "file_hash": file_hash,
                })
                global_index += 1

        if not rows:
            logger.warning(f"No text extracted from {file_name}")
            return {"success": False, "records": 0, "message": "No text extracted"}

        # Index into the SQLite FTS catalog (no embeddings / vector store).
        get_catalog_store().add_chunks(rows)
        all_chunks = rows  # for the record count below

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

        # Structured extraction (json-converter): build a per-document structured
        # JSON so factual/aggregate questions are answered EXACTLY. Best-effort —
        # never block ingestion if the LLM quota is exhausted or a chunk fails.
        structured_patients = None
        if settings.pdf_structured_extraction:
            try:
                from src.ingestion.pdf_structurer import PDFStructurer
                struct = PDFStructurer().structure_and_save(file_path, source_name=file_name)
                structured_patients = struct.get("patient_count")
                logger.info(f"PDF structurer: {structured_patients} patients extracted from {file_name}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"PDF structuring failed (non-fatal) for {file_name}: {e}")

        return {
            "success": True,
            "records": len(all_chunks),
            "structured_patients": structured_patients,
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