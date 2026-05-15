"""
POST /health-goals  — Tạo/ghi đè mục tiêu sức khỏe
GET  /health-goals  — Lấy mục tiêu hiện tại
PUT  /health-goals  — Cập nhật mục tiêu
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from auth import get_current_user
from database import supabase

router = APIRouter(prefix="/health-goals", tags=["Health Goals"])

# -- Schemas ---------------------------------------------------------------------------------

class HealthGoalBase(BaseModel):
    daily_calories: float = Field(..., gt=0, description="Calories cần nạp mỗi ngày (kcal)")
    protein_target: float = Field(..., gt=0, description="Protein mỗi ngày (g)")
    carbs_target: float = Field(..., gt=0, description="Carbs mỗi ngày (g)")
    fat_target: float = Field(..., gt=0, description="Fat mỗi ngày (g)")

class HealthGoalResponse(HealthGoalBase):
    goal_id: str
    user_id: str
    created_at: str

class UpdateHealthGoalRequest(BaseModel):
    daily_calories: Optional[float] = Field(None, gt=0)
    protein_target: Optional[float] = Field(None, gt=0)
    carbs_target: Optional[float] = Field(None, gt=0)
    fat_target: Optional[float] = Field(None, gt=0)

# -- Endpoints ---------------------------------------------------------------

@router.post("", response_model=HealthGoalResponse, summary="Tạo mục tiêu sức khỏe")
def create_goal(body: HealthGoalBase, user_id: str = Depends(get_current_user)):
    # UPSERT theo UNIQUE(user_id) — mỗi user chỉ có 1 goal active
    result = supabase.table("user_goals").upsert(
        {"user_id": user_id, **body.model_dump()},
        on_conflict="user_id"
    ).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Tạo mục tiêu thất bại.")
    return result.data[0]

@router.get("", response_model=HealthGoalResponse, summary="Lấy mục tiêu hiện tại")
def get_goal(user_id: str = Depends(get_current_user)):
    result = supabase.table("user_goals").select("*").eq("user_id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Chưa có mục tiêu sức khỏe. Hãy tạo mới.")
    return result.data

@router.put("", response_model=HealthGoalResponse, summary="Cập nhật mục tiêu")
def update_goal(body: UpdateHealthGoalRequest, user_id: str = Depends(get_current_user)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Không có thông tin nào để cập nhật.")

    result = supabase.table("user_goals").update(updates).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Chưa có mục tiêu. Hãy POST /health-goals trước.")
    return result.data[0]