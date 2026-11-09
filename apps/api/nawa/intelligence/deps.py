from nawa.core.config import Settings
from nawa.intelligence.gateway import LiteLLMClient, LLMClient


def get_llm_client() -> LLMClient:
    return LiteLLMClient()


def model_for_provider(settings: Settings, provider: str) -> str:
    """The wizard stores a provider; the concrete model name comes from the environment."""
    return settings.llm_model if provider == "deepseek" else settings.local_llm_model
