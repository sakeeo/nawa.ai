from nawa.core.errors import DomainError

LOCAL_MODEL_PREFIXES = ("ollama/", "ollama_chat/", "hosted_vllm/")


class OfflineModeError(DomainError):
    status_code = 403
    code = "offline_mode"
    title = "Offline Mode"


def is_local_model(model: str) -> bool:
    return model.startswith(LOCAL_MODEL_PREFIXES)


def ensure_allowed(model: str, offline: bool) -> None:
    if offline and not is_local_model(model):
        raise OfflineModeError(
            f"Model '{model}' uses an external provider and OFFLINE_MODE is enabled"
        )
