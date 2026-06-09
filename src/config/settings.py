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

    # Chunking
    chunk_size: int = Field(512, env="CHUNK_SIZE")
    chunk_overlap: int = Field(64, env="CHUNK_OVERLAP")

    # Retrieval
    vector_top_k: int = Field(5, env="VECTOR_TOP_K")
    sql_max_rows: int = Field(50, env="SQL_MAX_ROWS")

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