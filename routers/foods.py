"""
GET    /foods/search          — Tìm kiếm món ăn (system + custom của user)
POST   /foods                 — Tạo custom food
PUT    /foods/{food_id}       — Sửa custom food
DELETE /foods/{food_id}       — Xóa custom food
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from auth import get_current_user
from database import supabase

router = APIRouter(prefix="/foods", tags=["Foods"])

# -- Schemas -----------------------------------------------------------------

class FoodResponse(BaseModel):
    food_id: str
    name: str
    brand: Optional[str]
    user_id: Optional[str]
    serving_size: float
    calories: float
    protein: float
    carbohydrates: float
    fat: float
    dietary_fiber: Optional[float]
    sugars: Optional[float]
    sodium: Optional[float]
    saturated_fats: Optional[float]
    monounsaturated_fats: Optional[float]
    polyunsaturated_fats: Optional[float]
    cholesterol: Optional[float]
    water: Optional[float]
    vitamin_a: Optional[float]
    vitamin_b1: Optional[float]
    vitamin_b2: Optional[float]
    vitamin_b3: Optional[float]
    vitamin_b5: Optional[float]
    vitamin_b6: Optional[float]
    vitamin_b11: Optional[float]
    vitamin_b12: Optional[float]
    vitamin_c: Optional[float]
    vitamin_d: Optional[float]
    vitamin_e: Optional[float]
    vitamin_k: Optional[float]
    calcium: Optional[float]
    copper: Optional[float]
    iron: Optional[float]
    magnesium: Optional[float]
    manganese: Optional[float]
    phosphorus: Optional[float]
    potassium: Optional[float]
    selenium: Optional[float]
    zinc: Optional[float]
    nutrition_density: Optional[float]
    created_at: str

class CreateFoodRequest(BaseModel):
    name: str = Field(..., min_length=1)
    brand: Optional[str] = None
    serving_size: float = Field(100, gt=0, description="Gram")
    calories: float = Field(..., gt=0)
    protein: float = Field(..., ge=0)
    carbohydrates: float = Field(..., ge=0)
    fat: float = Field(..., ge=0)
    dietary_fiber: Optional[float] = Field(None, ge=0)
    sugars: Optional[float] = Field(None, ge=0)
    sodium: Optional[float] = Field(None, ge=0)
    saturated_fats: Optional[float] = Field(None, ge=0)
    monounsaturated_fats: Optional[float] = Field(None, ge=0)
    polyunsaturated_fats: Optional[float] = Field(None, ge=0)
    cholesterol: Optional[float] = Field(None, ge=0)

class UpdateFoodRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    brand: Optional[str] = None
    serving_size: Optional[float] = Field(None, gt=0)
    calories: Optional[float] = Field(None, gt=0)
    protein: Optional[float] = Field(None, ge=0)
    carbohydrates: Optional[float] = Field(None, ge=0)
    fat: Optional[float] = Field(None, ge=0)
    dietary_fiber: Optional[float] = Field(None, ge=0)
    sugars: Optional[float] = Field(None, ge=0)
    sodium: Optional[float] = Field(None, ge=0)
    saturated_fats: Optional[float] = Field(None, ge=0)
    monounsaturated_fats: Optional[float] = Field(None, ge=0)
    polyunsaturated_fats: Optional[float] = Field(None, ge=0)
    cholesterol: Optional[float] = Field(None, ge=0)

# -- Endpoints -----------------------------------------------------------------

@router.get("/search", summary="Tìm kiếm món ăn")
def search_foods(
    q: str = Query(..., min_length=1, description="Từ khóa tìm kiếm"),
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user),
):
    """
    Tìm theo tên — trả về system foods (user_id IS NULL)
    và custom foods của chính user.
    Dùng ilike để tìm không phân biệt hoa thường.
    """
    result = supabase.table("foods") \
        .select("food_id, name, brand, user_id, serving_size, calories, protein, carbohydrates, fat, dietary_fiber, sugars, sodium") \
        .ilike("name", f"%{q}%") \
        .or_(f"user_id.is.null,user_id.eq.{user_id}") \
        .limit(limit) \
        .execute()

    return {"total": len(result.data), "items": result.data}

@router.post("", response_model=FoodResponse, status_code=201, summary="Tạo custom food")
def create_food(body: CreateFoodRequest, user_id: str = Depends(get_current_user)):
    data = body.model_dump(exclude_none=True)
    data["user_id"] = user_id  # gắn owner

    result = supabase.table("foods").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Tạo món ăn thất bại.")
    return result.data[0]

@router.put("/{food_id}", response_model=FoodResponse, summary="Sửa custom food")
def update_food(food_id: str, body: UpdateFoodRequest, user_id: str = Depends(get_current_user)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Không có thông tin nào để cập nhật.")

    # Chỉ update food của chính user — tránh sửa system food hoặc food người khác
    result = supabase.table("foods") \
        .update(updates) \
        .eq("food_id", food_id) \
        .eq("user_id", user_id) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy món ăn hoặc bạn không có quyền sửa.")
    return result.data[0]

@router.delete("/{food_id}", status_code=204, summary="Xóa custom food")
def delete_food(food_id: str, user_id: str = Depends(get_current_user)):
    result = supabase.table("foods") \
        .delete() \
        .eq("food_id", food_id) \
        .eq("user_id", user_id) \
        .execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy món ăn hoặc bạn không có quyền xóa.")