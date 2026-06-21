from fastapi import APIRouter

router = APIRouter(prefix="/api/problems", tags=["problems"])

@router.get("")
async def get_problems():
    return []
