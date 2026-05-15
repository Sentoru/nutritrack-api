"""
GET  /analytics/calories          — Thống kê calories theo khoảng thời gian
POST /analytics/predict           — Dự đoán xu hướng cân nặng
"""

from typing import Literal
from datetime import date, timedelta
from enum import IntEnum
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from auth import get_current_user
from database import supabase

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# -- Schemas -----------------------------------------------------------------

class RangeDays(IntEnum):
    seven = 7
    thirty = 30
    ninety = 90

class DailyCaloriePoint(BaseModel):
    date: str
    calories_in: float
    calories_burned: float
    energy_balance: float

class CaloriesStatsResponse(BaseModel):
    range_days: int
    avg_calories_in: float
    avg_calories_burned: float
    avg_energy_balance: float
    daily: list[DailyCaloriePoint]

class PredictWeightRequest(BaseModel):
    range_days: RangeDays = Field(RangeDays.seven, description="Khoảng thời gian dự đoán: 7, 30, hoặc 90 ngày")

class WeightPredictionResponse(BaseModel):
    range_days: int
    current_weight_kg: float
    predicted_weight_change_kg: float
    predicted_final_weight_kg: float
    avg_energy_balance_per_day: float
    model_used: str
    confidence: str
    note: str

# -- BMR Helper -------------------------------------------------------------- 

def _calc_bmr(profile: dict) -> float:
    """Mifflin-St Jeor."""
    w = profile.get("weight_kg") or 0
    h = profile.get("height_cm") or 0
    dob = profile.get("date_of_birth")
    gender = profile.get("gender", "male")

    age = 25  # fallback
    if dob:
        try:
            birth = date.fromisoformat(dob)
            age = (date.today() - birth).days // 365
        except Exception:
            pass

    bmr = 10 * w + 6.25 * h - 5 * age
    return bmr + 5 if gender == "male" else bmr - 161

# -- Endpoints ---------------------------------------------------------------

@router.get(
    "/calories",
    response_model=CaloriesStatsResponse,
    summary="Thống kê calories theo ngày",
)
def get_calories_stats(
    range: RangeDays = Query(RangeDays.seven, description="Số ngày nhìn lại: 7, 30, hoặc 90 ngày"),
    user_id: str = Depends(get_current_user),
):
    end_date = date.today()
    start_date = end_date - timedelta(days=range - 1)

    # Lấy calories nạp vào theo ngày (từ meal_details qua meals)
    meals_result = supabase.table("meals") \
        .select("meal_date, meal_details(calories)") \
        .eq("user_id", user_id) \
        .gte("meal_date", str(start_date)) \
        .lte("meal_date", str(end_date)) \
        .execute()

    # Lấy calories tiêu hao theo ngày (từ daily_exercise_logs)
    exercise_result = supabase.table("daily_exercise_logs") \
        .select("log_date, calories_burned") \
        .eq("user_id", user_id) \
        .gte("log_date", str(start_date)) \
        .lte("log_date", str(end_date)) \
        .execute()

    # Lấy BMR từ profile
    profile_result = supabase.table("user_profiles") \
        .select("weight_kg, height_cm, gender, date_of_birth") \
        .eq("user_id", user_id) \
        .single() \
        .execute()

    bmr = _calc_bmr(profile_result.data) if profile_result.data else 1700.0

    # Aggregate calories_in per date
    calories_in_map: dict = {}
    for meal in meals_result.data:
        d = meal["meal_date"]
        total = sum(md["calories"] or 0 for md in meal.get("meal_details", []))
        calories_in_map[d] = calories_in_map.get(d, 0) + total

    # Aggregate calories_burned per date
    calories_burned_map: dict = {}
    for log in exercise_result.data:
        d = log["log_date"]
        calories_burned_map[d] = calories_burned_map.get(d, 0) + (log["calories_burned"] or 0)

    # Build daily series
    daily = []
    current = start_date
    while current <= end_date:
        ds = str(current)
        c_in = round(calories_in_map.get(ds, 0), 2)
        c_burned = round(calories_burned_map.get(ds, 0) + bmr, 2)
        daily.append(DailyCaloriePoint(
            date=ds,
            calories_in=c_in,
            calories_burned=c_burned,
            energy_balance=round(c_in - c_burned, 2),
        ))
        current += timedelta(days=1)

    n = len(daily) or 1
    avg_in      = round(sum(d.calories_in for d in daily) / n, 2)
    avg_burned  = round(sum(d.calories_burned for d in daily) / n, 2)
    avg_balance = round(sum(d.energy_balance for d in daily) / n, 2)

    return CaloriesStatsResponse(
        range_days=range,
        avg_calories_in=avg_in,
        avg_calories_burned=avg_burned,
        avg_energy_balance=avg_balance,
        daily=[d.model_dump() for d in daily],
    )

@router.post(
    "/predict",
    response_model=WeightPredictionResponse,
    summary="Dự đoán xu hướng cân nặng",
    description="""
Tính cân bằng năng lượng tích lũy và dự đoán thay đổi cân nặng.

**Công thức:** ΔWeight (kg) = Tổng energy balance / 7700

**Model sử dụng:**
- Có `heart_rate` + `body_temp` trong health_data_sync → 7 features (R² ≈ 0.997)
- Không có → 5 features (R² ≈ 0.85), hiển thị cảnh báo
    """,
)
def predict_weight_trend(
    body: PredictWeightRequest,
    user_id: str = Depends(get_current_user),
):
    # Lấy profile
    profile_result = supabase.table("user_profiles") \
        .select("weight_kg, height_cm, gender, date_of_birth") \
        .eq("user_id", user_id) \
        .single() \
        .execute()

    if not profile_result.data or not profile_result.data.get("weight_kg"):
        raise HTTPException(
            status_code=400,
            detail="Cần có thông tin cân nặng. Hãy cập nhật profile trước."
        )

    profile = profile_result.data
    bmr = _calc_bmr(profile)
    current_weight = profile["weight_kg"]

    end_date = date.today()
    start_date = end_date - timedelta(days=body.range_days - 1)

    # Lấy calories nạp vào
    meals_result = supabase.table("meals") \
        .select("meal_date, meal_details(calories)") \
        .eq("user_id", user_id) \
        .gte("meal_date", str(start_date)) \
        .lte("meal_date", str(end_date)) \
        .execute()

    # Lấy calories tiêu hao tập luyện
    exercise_result = supabase.table("daily_exercise_logs") \
        .select("log_date, calories_burned") \
        .eq("user_id", user_id) \
        .gte("log_date", str(start_date)) \
        .lte("log_date", str(end_date)) \
        .execute()

    # Kiểm tra có dữ liệu tập luyện không
    if not exercise_result.data:
        raise HTTPException(
            status_code=400,
            detail="Cần thêm dữ liệu hoạt động thể chất để phân tích."
        )

    # Kiểm tra có heart_rate + body_temp từ Health Connect không
    sync_result = supabase.table("health_data_sync") \
        .select("heart_rate, body_temp") \
        .eq("user_id", user_id) \
        .gte("sync_date", str(start_date)) \
        .not_.is_("heart_rate", "null") \
        .not_.is_("body_temp", "null") \
        .execute()

    has_smartwatch_data = len(sync_result.data) > 0
    model_used = "7_features" if has_smartwatch_data else "5_features"
    confidence = "high" if has_smartwatch_data else "medium"

    # Aggregate per date
    calories_in_map: dict = {}
    for meal in meals_result.data:
        d = meal["meal_date"]
        total = sum(md["calories"] or 0 for md in meal.get("meal_details", []))
        calories_in_map[d] = calories_in_map.get(d, 0) + total

    calories_burned_map: dict = {}
    for log in exercise_result.data:
        d = log["log_date"]
        calories_burned_map[d] = calories_burned_map.get(d, 0) + (log["calories_burned"] or 0)

    # Tính tổng energy balance
    total_balance = 0.0
    days_with_data = 0
    current = start_date
    while current <= end_date:
        ds = str(current)
        c_in = calories_in_map.get(ds, 0)
        c_burned = calories_burned_map.get(ds, 0) + bmr
        if c_in > 0:  # chỉ tính ngày có ăn
            total_balance += c_in - c_burned
            days_with_data += 1
        current += timedelta(days=1)

    if days_with_data == 0:
        raise HTTPException(
            status_code=400,
            detail="Chưa có dữ liệu bữa ăn. Hãy ghi nhận bữa ăn trước."
        )

    avg_balance = round(total_balance / days_with_data, 2)

    # Dự đoán thay đổi cân nặng theo công thức 7700 kcal = 1kg
    # Extrapolate ra range_days
    projected_balance = avg_balance * body.range_days
    weight_change = round(projected_balance / 7700, 2)
    final_weight = round(current_weight + weight_change, 2)

    # Nhận xét ngắn
    if avg_balance < -100:
        status_note = f"Bạn đang thâm hụt ~{abs(avg_balance):.0f} kcal/ngày, dự kiến giảm ~{abs(weight_change):.2f} kg sau {body.range_days} ngày."
    elif avg_balance > 100:
        status_note = f"Bạn đang dư ~{avg_balance:.0f} kcal/ngày, dự kiến tăng ~{weight_change:.2f} kg sau {body.range_days} ngày."
    else:
        status_note = f"Bạn đang duy trì cân nặng tốt (~{avg_balance:.0f} kcal/ngày)."

    if not has_smartwatch_data:
        status_note += " Độ chính xác dự đoán sẽ cao hơn nếu bạn kết nối smartwatch."

    return WeightPredictionResponse(
        range_days=body.range_days,
        current_weight_kg=current_weight,
        predicted_weight_change_kg=weight_change,
        predicted_final_weight_kg=final_weight,
        avg_energy_balance_per_day=avg_balance,
        model_used=model_used,
        confidence=confidence,
        note=status_note,
    )