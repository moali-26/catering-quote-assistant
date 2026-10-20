"""Server settings read from environment variables. No secrets have defaults."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    env: str
    dataset: str

    @property
    def is_production(self) -> bool:
        return self.env == 'production'


def load_settings() -> Settings:
    dataset = os.environ.get('APP_DATASET', 'sample')
    if dataset not in ('sample', 'full'):
        raise ValueError("APP_DATASET must be 'sample' or 'full'")
    return Settings(env=os.environ.get('APP_ENV', 'development'), dataset=dataset)
