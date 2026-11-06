from fastapi import APIRouter

from nawa.workspace import api_auth, api_invites, api_members, api_workspaces

router = APIRouter()
router.include_router(api_auth.router)
router.include_router(api_workspaces.router)
router.include_router(api_members.router)
router.include_router(api_invites.workspace_router)
router.include_router(api_invites.public_router)
