"""Server settings read from environment variables. No secrets have defaults."""
import os
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Settings:
    env: str
    dataset: str
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    owner_ids: Tuple[str, ...] = ()
    database_url: Optional[str] = None
    auth_backend: Optional[str] = None  # 'supabase', 'memory' (development only) or None
    llm_provider: Optional[str] = None  # 'anthropic', 'openai' or None (chat disabled)

    @property
    def is_production(self) -> bool:
        return self.env == 'production'

    @property
    def business_owner_id(self) -> Optional[str]:
        """The single demo business belongs to the first configured owner account."""
        return self.owner_ids[0] if self.owner_ids else None


def _owner_ids(raw: str) -> Tuple[str, ...]:
    return tuple(part.strip().lower() for part in raw.split(',') if part.strip())


def load_settings() -> Settings:
    env = os.environ.get('APP_ENV', 'development')
    dataset = os.environ.get('APP_DATASET', 'sample')
    if dataset not in ('demo', 'sample', 'full'):
        raise ValueError("APP_DATASET must be 'demo', 'sample' or 'full'")
    supabase_url = (os.environ.get('SUPABASE_URL') or '').rstrip('/') or None
    supabase_key = os.environ.get('SUPABASE_PUBLISHABLE_KEY') or None
    requested = os.environ.get('AUTH_BACKEND', '').strip().lower()
    if requested == 'memory':
        if env == 'production':
            raise ValueError('AUTH_BACKEND=memory is for local development only')
        backend = 'memory'
    elif supabase_url and supabase_key:
        backend = 'supabase'
    else:
        backend = None
    return Settings(
        env=env,
        dataset=dataset,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        owner_ids=_owner_ids(os.environ.get('OWNER_USER_IDS', '')),
        # Tolerate stray spaces/quotes pasted into the dashboard.
        database_url=(os.environ.get('QUOTE_DATABASE_URL') or '').strip().strip('"\'').strip() or None,
        auth_backend=backend,
        llm_provider=_llm_provider(),
    )


def _llm_provider() -> Optional[str]:
    """LLM_PROVIDER picks the chat model; default Claude when its key is present."""
    requested = os.environ.get('LLM_PROVIDER', '').strip().lower()
    if requested in ('anthropic', 'claude'):
        return 'anthropic' if os.environ.get('ANTHROPIC_API_KEY') else None
    if requested in ('openai', 'gpt'):
        return 'openai' if os.environ.get('OPENAI_API_KEY') and os.environ.get('OPENAI_MODEL') else None
    if requested == 'scripted':
        return 'scripted' if os.environ.get('APP_ENV', 'development') != 'production' else None
    if requested:
        raise ValueError("LLM_PROVIDER must be 'anthropic', 'openai' or 'scripted' (local only)")
    return 'anthropic' if os.environ.get('ANTHROPIC_API_KEY') else None
