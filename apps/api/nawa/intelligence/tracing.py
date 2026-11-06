import os

import litellm

from nawa.core.config import Settings


def configure_litellm(settings: Settings) -> None:
    """Disable LiteLLM telemetry and send traces to the self-hosted Langfuse when configured."""
    litellm.telemetry = False
    secret = settings.langfuse_secret_key
    if settings.langfuse_host and settings.langfuse_public_key and secret:
        os.environ["LANGFUSE_HOST"] = settings.langfuse_host
        os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
        os.environ["LANGFUSE_SECRET_KEY"] = secret.get_secret_value()
        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]
    else:
        litellm.success_callback = []
        litellm.failure_callback = []
