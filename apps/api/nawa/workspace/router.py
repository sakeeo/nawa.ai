from fastapi import APIRouter

from nawa.workspace import api_auth

router = APIRouter()
router.include_router(api_auth.router)
