from fastapi import APIRouter

from nawa.workspace import api_auth, api_workspaces

router = APIRouter()
router.include_router(api_auth.router)
router.include_router(api_workspaces.router)
