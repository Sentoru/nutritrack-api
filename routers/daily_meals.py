"""
POST   /daily-meals                        — Thêm món vào nhật ký bữa ăn
GET    /daily-meals?date=YYYY-MM-DD        — Lấy nhật ký bữa ăn trong ngày
PUT    /daily-meals/{meal_detail_id}       — Di chuyển món sang bữa khác / đổi quantity
DELETE /daily-meals/{meal_detail_id}       — Xóa món khỏi bữa ăn
"""

from typing import Optional, Literal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from auth import get_current_user
from database import supabase

router = APIRouter(prefix="/daily-meals", tags=["Daily Meals"])

MealType = Literal["breakfast", "lunch", "dinner", "snacks"]

# -- Schemas ---------------------------------------------------------------

class AddMealRequest(BaseModel):
    food_id: str = Field(..., description="UUID của food")
    meal_type: MealType
    quantity: float = Field(1.0, gt=0, description="Số serving")
    meal_date: Optional[date] = Field(None, description="YYYY-MM-DD, mặc định hôm nay")

class MealDetailResponse(BaseModel):
    meal_detail_id: str
    meal_id: str
    food_id: str
    quantity: float
    calories: float
    protein: float
    carbohydrates: float
    fat: float
    created_at: str

class UpdateMealDetailRequest(BaseModel):
    meal_type: Optional[MealType] = Field(None, description="Di chuyển sang bữa khác")
    quantity: Optional[float] = Field(None, gt=0)

class DailyMealSummary(BaseModel):
    meal_date: str
    total_calories: float
    total_protein: float
    total_carbohydrates: float
    total_fat: float
    meals: dict  # {breakfast: [...], lunch: [...], dinner: [...], snacks: [...]}

# -- Helper ------------------------------------------------------------------

def _get_or_create_meal(user_id: str, meal_type: str, meal_date: str) -> str:
    """Lấy meal_id hiện có hoặc tạo mới nếu chưa có."""
    existing = supabase.table("meals") \
        .select("meal_id") \
        .eq("user_id", user_id) \
        .eq("meal_type", meal_type) \
        .eq("meal_date", meal_date) \
        .execute()

    if existing.data:
        return existing.data[0]["meal_id"]

    created = supabase.table("meals").insert({
        "user_id": user_id,
        "meal_type": meal_type,
        "meal_date": meal_date,
    }).execute()

    return created.data[0]["meal_id"]

def _calc_nutrition(food: dict, quantity: float) -> dict:
    """Tính dinh dưỡng theo số serving."""
    return {
        "calories":      round((food["calories"] or 0) * quantity, 2),
        "protein":       round((food["protein"] or 0) * quantity, 4),
        "carbohydrates": round((food["carbohydrates"] or 0) * quantity, 4),
        "fat":           round((food["fat"] or 0) * quantity, 4),
    }

# -- Endpoints -------------------------------------------------------------

@router.post("", response_model=MealDetailResponse, status_code=201, summary="Thêm món vào nhật ký")
def add_meal(body: AddMealRequest, user_id: str = Depends(get_current_user)):
    today = str(body.meal_date or date.today())

    # Lấy thông tin dinh dưỡng của food
    food_result = supabase.table("foods") \
        .select("calories, protein, carbohydrates, fat") \
        .eq("food_id", body.food_id) \
        .single() \
        .execute()

    if not food_result.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy món ăn.")

    meal_id = _get_or_create_meal(user_id, body.meal_type, today)
    nutrition = _calc_nutrition(food_result.data, body.quantity)

    result = supabase.table("meal_details").insert({
        "meal_id":  meal_id,
        "food_id":  body.food_id,
        "quantity": body.quantity,
        **nutrition,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Thêm món thất bại.")
    return result.data[0]

@router.get("", response_model=DailyMealSummary, summary="Lấy nhật ký bữa ăn trong ngày")
def get_daily_meals(
    meal_date: Optional[date] = Query(None, description="YYYY-MM-DD, mặc định hôm nay"),
    user_id: str = Depends(get_current_user),
):
    today = str(meal_date or date.today())

    # Lấy tất cả meals trong ngày
    meals_result = supabase.table("meals") \
        .select("meal_id, meal_type") \
        .eq("user_id", user_id) \
        .eq("meal_date", today) \
        .execute()

    meals_by_type: dict = {"breakfast": [], "lunch": [], "dinner": [], "snacks": []}
    totals = {"calories": 0.0, "protein": 0.0, "carbohydrates": 0.0, "fat": 0.0}

    for meal in meals_result.data:
        details = supabase.table("meal_details") \
            .select("meal_detail_id, food_id, quantity, calories, protein, carbohydrates, fat, created_at, foods(name, brand)") \
            .eq("meal_id", meal["meal_id"]) \
            .execute()

        for d in details.data:
            meals_by_type[meal["meal_type"]].append(d)
            totals["calories"]      += d["calories"] or 0
            totals["protein"]       += d["protein"] or 0
            totals["carbohydrates"] += d["carbohydrates"] or 0
            totals["fat"]           += d["fat"] or 0

    return {
        "meal_date":        today,
        "total_calories":   round(totals["calories"], 2),
        "total_protein":    round(totals["protein"], 4),
        "total_carbohydrates": round(totals["carbohydrates"], 4),
        "total_fat":        round(totals["fat"], 4),
        "meals":            meals_by_type,
    }

@router.put("/{meal_detail_id}", response_model=MealDetailResponse, summary="Sửa/di chuyển món ăn")
def update_meal_detail(
    meal_detail_id: str,
    body: UpdateMealDetailRequest,
    user_id: str = Depends(get_current_user),
):
    if not body.meal_type and not body.quantity:
        raise HTTPException(status_code=400, detail="Cần ít nhất meal_type hoặc quantity.")

    # Verify ownership qua join meals
    detail = supabase.table("meal_details") \
        .select("meal_detail_id, meal_id, food_id, quantity, calories, protein, carbohydrates, fat, created_at, meals!inner(user_id, meal_date, meal_type)") \
        .eq("meal_detail_id", meal_detail_id) \
        .single() \
        .execute()

    if not detail.data or detail.data["meals"]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy hoặc không có quyền.")

    current = detail.data
    updates = {}

    # Đổi bữa ăn
    if body.meal_type and body.meal_type != current["meals"]["meal_type"]:
        new_meal_id = _get_or_create_meal(
            user_id, body.meal_type, current["meals"]["meal_date"]
        )
        updates["meal_id"] = new_meal_id

    # Đổi quantity → tính lại dinh dưỡng
    if body.quantity and body.quantity != current["quantity"]:
        food_result = supabase.table("foods") \
            .select("calories, protein, carbohydrates, fat") \
            .eq("food_id", current["food_id"]) \
            .single() \
            .execute()
        updates["quantity"] = body.quantity
        updates.update(_calc_nutrition(food_result.data, body.quantity))

    result = supabase.table("meal_details") \
        .update(updates) \
        .eq("meal_detail_id", meal_detail_id) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Cập nhật thất bại.")
    return result.data[0]

@router.delete("/{meal_detail_id}", status_code=204, summary="Xóa món khỏi bữa ăn")
def delete_meal_detail(meal_detail_id: str, user_id: str = Depends(get_current_user)):
    # Verify ownership qua join
    detail = supabase.table("meal_details") \
        .select("meal_detail_id, meals!inner(user_id)") \
        .eq("meal_detail_id", meal_detail_id) \
        .single() \
        .execute()

    if not detail.data or detail.data["meals"]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Không tìm thấy hoặc không có quyền.")

    supabase.table("meal_details").delete().eq("meal_detail_id", meal_detail_id).execute()