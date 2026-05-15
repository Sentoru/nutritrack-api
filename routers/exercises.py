"""
GET    /exercises/search           — Tìm kiếm bài tập
POST   /exercises                  — Tạo custom exercise
PUT    /exercises/{exercise_id}    — Sửa custom exercise
DELETE /exercises/{exercise_id}    — Xóa custom exercise
"""

from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from auth import get_current_user
from database import supabase

router = APIRouter(prefix="/exercises", tags=["Exercises"])

ExerciseType = Literal["cardio", "strength"]

# -- Schemas --------------------------------------------------------------------------------

class ExerciseResponse(BaseModel):
    exercise_id: str
    name: str
    exercise_type: ExerciseType
    user_id: Optional[str]
    calories_per_min: Optional[float]
    description: Optional[str]
    created_at: str

class CreateExerciseRequest(BaseModel):
    name: str = Field(..., min_length=1)
    exercise_type: ExerciseType
    calories_per_min: Optional[float] = Field(None, gt=0)
    description: Optional[str] = None

class UpdateExerciseRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    exercise_type: Optional[ExerciseType] = None
    calories_per_min: Optional[float] = Field(None, gt=0)
    description: Optional[str] = None

# -- Endpoints -------------------------------------------------------------------------------

@router.get("/search", summary="Tìm kiếm bài tập")
def search_exercises(
    q: str = Query(..., min_length=1, description="Từ khóa tìm kiếm"),
    exercise_type: Optional[ExerciseType] = Query(None, description="Lọc theo loại: cardio | strength"),
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
):
    query = supabase.table("exercises") \
        .select("exercise_id, name, exercise_type, user_id, calories_per_min, description") \
        .ilike("name", f"%{q}%") \
        .or_(f"user_id.is.null,user_id.eq.{user_id}")

    if exercise_type:
        query = query.eq("exercise_type", exercise_type)

    result = query.limit(limit).execute()
    return {"total": len(result.data), "items": result.data}

@router.post("", response_model=ExerciseResponse, status_code=201, summary="Tạo custom exercise")
def create_exercise(body: CreateExerciseRequest, user_id: str = Depends(get_current_user)):
    data = body.model_dump(exclude_none=True)
    data["user_id"] = user_id

    result = supabase.table("exercises").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Tạo bài tập thất bại.")
    return result.data[0]

@router.put("/{exercise_id}", response_model=ExerciseResponse, summary="Sửa custom exercise")
def update_exercise(exercise_id: str, body: UpdateExerciseRequest, user_id: str = Depends(get_current_user)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Không có thông tin nào để cập nhật.")

    result = supabase.table("exercises") \
        .update(updates) \
        .eq("exercise_id", exercise_id) \
        .eq("user_id", user_id) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài tập hoặc không có quyền sửa.")
    return result.data[0]

@router.delete("/{exercise_id}", status_code=204, summary="Xóa custom exercise")
def delete_exercise(exercise_id: str, user_id: str = Depends(get_current_user)):
    result = supabase.table("exercises") \
        .delete() \
        .eq("exercise_id", exercise_id) \
        .eq("user_id", user_id) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài tập hoặc không có quyền xóa.")