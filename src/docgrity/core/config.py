"""Application settings loaded from environment (.env for local development)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://docgrity:docgrity@localhost:5432/docgrity"
    redis_url: str = "redis://localhost:6379/0"

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    # Google Gemini via its OpenAI-compatible endpoint.
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    # GitHub Models (https://models.github.ai) — a GitHub PAT with models scope.
    github_token: str = ""
    github_models_base_url: str = "https://models.github.ai/inference"
    # Local/self-hosted OpenAI-compatible endpoints.
    ollama_base_url: str = "http://localhost:11434/v1"
    llm_custom_base_url: str = ""
    llm_custom_api_key: str = ""

    # Capability → "provider:model" routing (configuration, not code constants).
    # Providers: openai | anthropic | github | ollama | custom, or any provider
    # PydanticAI can infer (google-gla, groq, mistral, cohere, bedrock, ...).
    llm_reasoning_high_model: str = "anthropic:claude-sonnet-4-20250514"
    llm_reasoning_fast_model: str = "openai:gpt-4o-mini"
    llm_classification_model: str = "openai:gpt-4o-mini"
    llm_embedding_model: str = "openai:text-embedding-3-small"
    # Optional "provider:model" used automatically when the primary provider
    # errors (rate limit, outage). Empty = no fallback.
    llm_fallback_model: str = ""
    # Requested embedding dimensions (0 = provider default). Must match the
    # pgvector column (1536). Set to 1536 for gemini-embedding-001.
    llm_embedding_dimensions: int = 0

    confluence_base_url: str = ""
    confluence_email: str = ""
    confluence_api_token: str = ""
    # OAuth 2.0 (3LO) / Forge-mediated bearer token — production auth path.
    confluence_access_token: str = ""

    # Jira connector (defaults to the Confluence site + credentials when empty).
    jira_base_url: str = ""

    # GitHub connector (repo read access; separate from the Models PAT above).
    github_connector_token: str = ""
    github_api_base_url: str = "https://api.github.com"
    # Comma-separated "owner/repo" list the code-doc drift check may read.
    github_repos: str = ""

    # Slack connector (bot token, read scopes: channels:history, channels:read).
    slack_bot_token: str = ""
    # Comma-separated channel IDs to watch for tribal knowledge.
    slack_channels: str = ""

    api_secret_key: str = "change-me"

    # Forge Remote auth (production): FIT verification.
    forge_app_id: str = ""  # ari:cloud:ecosystem::app/<uuid>
    forge_jwks_url: str = "https://forge.cdn.prod.atlassian-dev.net/.well-known/jwks.json"
    # Dev-only auth path (X-API-Key + X-Tenant-Id). Off by default; enable
    # explicitly for local development only — never in production.
    dev_auth_enabled: bool = False

    log_level: str = "INFO"

    # Action-policy thresholds (configuration, not code constants)
    duplicate_confidence_threshold: float = 0.75
    contradiction_confidence_threshold: float = 0.75
    open_question_confidence_threshold: float = 0.6


@lru_cache
def get_settings() -> Settings:
    return Settings()
