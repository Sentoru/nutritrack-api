"""
GET  /users/profile  — Lấy thông tin user
PUT  /users/profile  — Cập nhật thông tin user
"""

from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from auth import get_current_user
from database import supabase

router = APIRouter(prefix="/users", tags=["Users"])

# -- Schemas -------------------------------------------------------------------

class UserProfileResponse(BaseModel):
    user_id: str
    full_name: Optional[str]
    gender: Optional[str]
    date_of_birth: Optional[str]
    height_cm: Optional[float]
    weight_kg: Optional[float]
    goal_weight: Optional[float]
    activity_level: Optional[str]
    goal: Optional[str]
    updated_at: Optional[str]

class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = Field(None, description="Họ tên")
    gender: Optional[Literal["male", "female", "other"]] = None
    date_of_birth: Optional[str] = Field(None, description="YYYY-MM-DD")
    height_cm: Optional[float] = Field(None, gt=0, lt=300)
    weight_kg: Optional[float] = Field(None, gt=0, lt=500)
    goal_weight: Optional[float] = Field(None, gt=0, lt=500)
    activity_level: Optional[Literal[
        "sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"
    ]] = None
    goal: Optional[Literal["lose_fat", "maintain", "gain_weight"]] = None

# -- Endpoints ---------------------------------------------------------------

@router.get("/profile", response_model=UserProfileResponse, summary="Lấy thông tin người dùng")
def get_profile(user_id: str = Depends(get_current_user)):
    result = supabase.table("user_profiles").select("*").eq("user_id", user_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Chưa có profile. Hãy cập nhật thông tin lần đầu.")
    return result.data

@router.put("/profile", response_model=UserProfileResponse, summary="Cập nhật thông tin người dùng")
def update_profile(body: UpdateProfileRequest, user_id: str = Depends(get_current_user)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Không có thông tin nào để cập nhật.")

    from datetime import datetime, timezone
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()

    # UPSERT — tạo mới nếu chưa có, update nếu đã có
    result = supabase.table("user_profiles").upsert(
        {"user_id": user_id, **updates}
    ).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Cập nhật thất bại.")
    return result.data[0]