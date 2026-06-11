"""
Application configuration loaded from environment variables.
All settings have defaults so the app can start with a minimal .env.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    # Groq LLM
    groq_api_key: str = Field(..., env="GROQ_API_KEY")
    groq_model: str = Field("llama-3.3-70b-versatile", env="GROQ_MODEL")
    # Cheaper/faster model for the many per-chunk structured-extraction calls,
    # so document structuring doesn't burn the larger model's daily quota.
    groq_extraction_model: str = Field("llama-3.1-8b-instant", env="GROQ_EXTRACTION_MODEL")
    groq_max_tokens: int = Field(2048, env="GROQ_MAX_TOKENS")
    groq_temperature: float = Field(0.1, env="GROQ_TEMPERATURE")

    # Database
    database_url: str = Field(..., env="DATABASE_URL")
    test_database_url: Optional[str] = Field(None, env="TEST_DATABASE_URL") 

    # ChromaDB
    chroma_persist_dir: str = Field("./chroma_db", env="CHROMA_PERSIST_DIR")
    chroma_collection_name: str = Field("investigator_docs", env="CHROMA_COLLECTION_NAME")

    # Embeddings
    embedding_model: str = Field(
        "sentence-transformers/all-MiniLM-L6-v2", env="EMBEDDING_MODEL"
    )
    embedding_cache_dir: str = Field("./embedding_cache", env="EMBEDDING_CACHE_DIR")

    # Chunking — larger chunks keep each patient narrative intact (less
    # fragmentation = higher answer accuracy on large documents).
    chunk_size: int = Field(1200, env="CHUNK_SIZE")
    chunk_overlap: int = Field(200, env="CHUNK_OVERLAP")

    # Retrieval — retrieve more chunks so answers on large corpora see enough
    # evidence instead of a thin 5-chunk slice.
    vector_top_k: int = Field(12, env="VECTOR_TOP_K")
    sql_max_rows: int = Field(20, env="SQL_MAX_ROWS")

    # Document structuring (json-converter): extract patients/study fields from
    # narrative PDFs into a per-document structured JSON so factual/aggregate
    # questions are answered exactly, not approximately.
    pdf_structured_extraction: bool = Field(True, env="PDF_STRUCTURED_EXTRACTION")
    json_store_dir: str = Field("./json_store", env="JSON_STORE_DIR")
    # Chunk size used for LLM extraction (bigger than the embedding chunk so each
    # call sees a whole patient record; fewer calls = less quota).
    extraction_chunk_size: int = Field(9000, env="EXTRACTION_CHUNK_SIZE")

    # Memory
    memory_window_size: int = Field(10, env="MEMORY_WINDOW_SIZE")
    max_session_age_days: int = Field(30, env="MAX_SESSION_AGE_DAYS")

    # App
    app_host: str = Field("0.0.0.0", env="APP_HOST")
    app_port: int = Field(8000, env="APP_PORT")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    data_dir: str = Field("./data", env="DATA_DIR")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore" 


# Single instance used everywhere
settings = Settings()