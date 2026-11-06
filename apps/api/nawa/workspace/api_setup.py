from fastapi import APIRouter

from nawa.workspace import repository, setup_service
from nawa.workspace.deps import SessionDep, SettingsDep
from nawa.workspace.schemas import SetupRequest, SetupStatus, UserOut

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatus)
async def setup_status(session: SessionDep, settings: SettingsDep) -> SetupStatus:
    return SetupStatus(
        setup_required=await repository.setup_required(session),
        providers=setup_service.available_providers(settings),
    )


@router.post("", status_code=201, response_model=UserOut)
async def run_setup(body: SetupRequest, session: SessionDep, settings: SettingsDep) -> UserOut:
    user = await setup_service.complete_setup(session, settings, body)
    return UserOut.model_validate(user)
