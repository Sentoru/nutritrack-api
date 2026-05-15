"""
POST   /daily-exercises                       — Thêm bài tập vào nhật ký
GET    /daily-exercises?date=YYYY-MM-DD       — Lấy nhật ký bài tập trong ngày
PUT    /daily-exercises/{log_id}              — Sửa log bài tập
DELETE /daily-exercises/{log_id}              — Xóa log bài tập
"""

from typing import Optional, Literal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from auth import get_current_user
from database import supabase

router = APIRouter(prefix="/daily-exercises", tags=["Daily Exercises"])

ExerciseType = Literal["cardio", "strength"]

# -- Schemas -------------------------------------------------------------

class AddExerciseLogRequest(BaseModel):
    exercise_id: str
    exercise_type: ExerciseType
    log_date: Optional[date] = None          # mặc định hôm nay
    calories_burned: float = Field(..., gt=0)

    # Cardio
    duration_min: Optional[float] = Field(None, gt=0)

    # Strength
    sets: Optional[int] = Field(None, gt=0)
    reps: Optional[int] = Field(None, gt=0)
    weight_kg: Optional[float] = Field(None, ge=0)

    # Smartwatch / Health Connect
    heart_rate: Optional[float] = Field(None, gt=0, lt=250)
    body_temp: Optional[float] = Field(None, gt=35.0, lt=42.0)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_by_type(self):
        if self.exercise_type == "cardio" and self.duration_min is None:
            raise ValueError("Cardio yêu cầu duration_min.")
        if self.exercise_type == "strength":
            if self.sets is None or self.reps is None:
                raise ValueError("Strength yêu cầu sets và reps.")
        return self

class ExerciseLogResponse(BaseModel):
    log_id: str
    user_id: str
    exercise_id: str
    log_date: str
    exercise_type: ExerciseType
    duration_min: Optional[float]
    sets: Optional[int]
    reps: Optional[int]
    weight_kg: Optional[float]
    calories_burned: float
    heart_rate: Optional[float]
    body_temp: Optional[float]
    notes: Optional[str]
    created_at: str

class UpdateExerciseLogRequest(BaseModel):
    calories_burned: Optional[float] = Field(None, gt=0)
    duration_min: Optional[float] = Field(None, gt=0)
    sets: Optional[int] = Field(None, gt=0)
    reps: Optional[int] = Field(None, gt=0)
    weight_kg: Optional[float] = Field(None, ge=0)
    heart_rate: Optional[float] = Field(None, gt=0, lt=250)
    body_temp: Optional[float] = Field(None, gt=35.0, lt=42.0)
    notes: Optional[str] = None

class DailyExerciseSummary(BaseModel):
    log_date: str
    total_calories_burned: float
    total_duration_min: float
    logs: list

# -- Endpoints ---------------------------------------------------------

@router.post("", response_model=ExerciseLogResponse, status_code=201, summary="Thêm bài tập vào nhật ký")
def add_exercise_log(body: AddExerciseLogRequest, user_id: str = Depends(get_current_user)):
    # Verify exercise tồn tại
    ex = supabase.table("exercises") \
        .select("exercise_id") \
        .eq("exercise_id", body.exercise_id) \
        .single() \
        .execute()

    if not ex.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy bài tập.")

    data = body.model_dump(exclude_none=True)
    data["user_id"] = user_id
    data["log_date"] = str(body.log_date or date.today())

    result = supabase.table("daily_exercise_logs").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Thêm bài tập thất bại.")
    return result.data[0]

@router.get("", response_model=DailyExerciseSummary, summary="Lấy nhật ký bài tập trong ngày")
def get_daily_exercises(
    log_date: Optional[date] = Query(None, description="YYYY-MM-DD, mặc định hôm nay"),
    user_id: str = Depends(get_current_user),
):
    today = str(log_date or date.today())

    result = supabase.table("daily_exercise_logs") \
        .select("*, exercises(name, exercise_type, calories_per_min)") \
        .eq("user_id", user_id) \
        .eq("log_date", today) \
        .order("created_at") \
        .execute()

    logs = result.data
    total_calories = sum(l["calories_burned"] for l in logs)
    total_duration = sum(l["duration_min"] or 0 for l in logs)

    return {
        "log_date": today,
        "total_calories_burned": round(total_calories, 2),
        "total_duration_min": round(total_duration, 2),
        "logs": logs,
    }

@router.put("/{log_id}", response_model=ExerciseLogResponse, summary="Sửa log bài tập")
def update_exercise_log(
    log_id: str,
    body: UpdateExerciseLogRequest,
    user_id: str = Depends(get_current_user),
):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Không có thông tin nào để cập nhật.")

    result = supabase.table("daily_exercise_logs") \
        .update(updates) \
        .eq("log_id", log_id) \
        .eq("user_id", user_id) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy log hoặc không có quyền.")
    return result.data[0]

@router.delete("/{log_id}", status_code=204, summary="Xóa log bài tập")
def delete_exercise_log(log_id: str, user_id: str = Depends(get_current_user)):
    result = supabase.table("daily_exercise_logs") \
        .delete() \
        .eq("log_id", log_id) \
        .eq("user_id", user_id) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy log hoặc không có quyền.")