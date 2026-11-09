from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from nawa.core.errors import ConflictError
from nawa.intelligence.deps import get_llm_client, model_for_provider
from nawa.intelligence.gateway import ChatMessage, LLMClient, LLMGateway, TraceInfo
from nawa.intelligence.prompts import PromptRegistry
from nawa.workspace import repository
from nawa.workspace.deps import AdminUser, SessionDep, SettingsDep, require_csrf

router = APIRouter(prefix="/api/v1/llm", tags=["llm"], dependencies=[Depends(require_csrf)])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


@router.post("/chat")
async def chat(
    body: ChatRequest,
    user: AdminUser,
    settings: SettingsDep,
    session: SessionDep,
    client: Annotated[LLMClient, Depends(get_llm_client)],
) -> ChatResponse:
    instance = await repository.get_instance_settings(session)
    if not instance.setup_completed or instance.ai_provider is None:
        raise ConflictError("Setup has not been completed")
    prompt = PromptRegistry().get("ping")
    gateway = LLMGateway(client, settings, model=model_for_provider(settings, instance.ai_provider))
    result = await gateway.chat(
        [ChatMessage("system", prompt.render()), ChatMessage("user", body.message)],
        TraceInfo(
            name="llm-test",
            user_id=str(user.id),
            prompt_name=prompt.name,
            prompt_version=prompt.version,
        ),
    )
    return ChatResponse(
        content=result.content,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        cost_usd=result.cost_usd,
    )
