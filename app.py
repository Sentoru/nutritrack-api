from typing import Optional, Literal, List
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timedelta, timezone
import joblib
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

# -- Import shared modules -----------------------------------------------------

from auth import get_current_user
from database import supabase

# -- Import routers ------------------------------------------------------------

from routers.users import router as users_router
from routers.health_goals import router as health_goals_router
from routers.foods import router as foods_router
from routers.daily_meals import router as daily_meals_router
from routers.exercises import router as exercises_router
from routers.daily_exercises import router as daily_exercises_router
from routers.sync import router as sync_router
from routers.analytics import router as analytics_router

# =====================
# SWAGGER METADATA
# =====================
description = """
## NutriTrack API
 
API backend cho ứng dụng quản lý dinh dưỡng và sức khỏe cá nhân.
 
### Authentication
Tất cả endpoint (trừ `/health` và `/predict/calories`) yêu cầu JWT token từ Supabase Auth.
Click **Authorize** -> nhập token (không cần gõ "Bearer").

### Modules
| Module | Mô tả |
|---|---|
| Users | Quản lý profile người dùng |
| Health Goals | Mục tiêu calo/dinh dưỡng hàng ngày |
| Foods | Tìm kiếm và tạo custom food |
| Daily Meals | Nhật ký bữa ăn |
| Exercises | Tìm kiếm và tạo custom exercise |
| Daily Exercises | Nhật ký bài tập |
| Health Data Sync | Đồng bộ từ Health Connect (Android) |
| Analytics | Thống kê và dự đoán xu hướng cân nặng |
| Prediction (legacy) | Dự đoán calories từ XGBoost model |
"""

app = FastAPI(
    title="NutriTrack API",
    description=description,
    version="3.0.0",
    openapi_tags=[
        {"name": "Health",           "description": "Trạng thái API"},
        {"name": "Users",            "description": "Profile người dùng"},
        {"name": "Health Goals",     "description": "Mục tiêu sức khỏe hàng ngày"},
        {"name": "Foods",            "description": "Tìm kiếm và quản lý món ăn"},
        {"name": "Daily Meals",      "description": "Nhật ký bữa ăn"},
        {"name": "Exercises",        "description": "Tìm kiếm và quản lý bài tập"},
        {"name": "Daily Exercises",  "description": "Nhật ký bài tập"},
        {"name": "Health Data Sync", "description": "Đồng bộ Health Connect"},
        {"name": "Analytics",        "description": "Thống kê và dự đoán cân nặng"},
        {"name": "Prediction",       "description": "XGBoost calories prediction (legacy)"},
        {"name": "History",          "description": "Lịch sử predictions (legacy)"},
    ]
)

# -- Mount routers -----------------------------------------------------

app.include_router(users_router)
app.include_router(health_goals_router)
app.include_router(foods_router)
app.include_router(daily_meals_router)
app.include_router(exercises_router)
app.include_router(daily_exercises_router)
app.include_router(sync_router)
app.include_router(analytics_router)

# =====================
# LOAD ML MODELS
# =====================
try:
    model_7 = joblib.load("models/xgb_calories_7feat.joblib")
    model_5 = joblib.load("models/xgb_calories_5feat.joblib")
    label_encoder = joblib.load("models/label_encoder_sex.joblib")
except FileNotFoundError as e:
    raise RuntimeError(f"Không tìm thấy file model: {e}")
except Exception as e:
    raise RuntimeError(f"Lỗi khi tải model: {e}")

# =====================
# SCHEMAS
# =====================
class PredictRequest(BaseModel):
    sex: Literal["male", "female"] = Field(..., example="male")
    age: float = Field(..., gt=0, lt=120)
    height: float = Field(..., gt=0, lt=300)
    weight: float = Field(..., gt=0, lt=300)
    duration: float = Field(..., gt=0)
    heart_rate: Optional[float] = Field(None, gt=0, lt=250)
    body_temp: Optional[float] = Field(None, gt=35.0, lt=42.0)
 
    model_config = {
        "json_schema_extra": {
            "examples": [
                {"summary": "5 features", "value": {"sex": "male", "age": 25, "height": 170.0, "weight": 70.0, "duration": 30.0}},
                {"summary": "7 features", "value": {"sex": "male", "age": 25, "height": 170.0, "weight": 70.0, "duration": 30.0, "heart_rate": 120.0, "body_temp": 37.5}},
            ]
        }
    }

class PredictResponse(BaseModel):
    calories_predicted: float
    model_used: str
    confidence: str

class SavePredictionRequest(BaseModel):
    predicted_calories: int = Field(..., gt=0)
    features_used: Literal[5, 7]

    @field_validator("predicted_calories", mode="before")
    @classmethod
    def coerce_to_int(cls, v):
        return round(float(v))

class SavePredictionResponse(BaseModel):
    prediction_id: str
    evaluation_date: str
    message: str

class PredictionHistoryItem(BaseModel):
    id: str
    predicted_calories: int
    actual_weight_change: Optional[float]
    features_used: int
    status: str
    timestamp: str
    evaluation_date: str

class GetHistoryResponse(BaseModel):
    user_id: str
    total: int
    predictions: List[PredictionHistoryItem]

# =====================
# ENDPOINTS
# =====================
@app.get("/")
def root():
    return {"message": "NutriTrack API v3.0 is running"}

@app.get("/health", tags=["Health"], summary="Health Check", description="Kiểm tra API và models đã sẵn sàng chưa.")
def health_check():
    return {
        "status": "ok",
        "models_loaded": {
            "model_5": model_5 is not None,
            "model_7": model_7 is not None,
            "label_encoder": label_encoder is not None
        }
    }

@app.post("/predict/calories", response_model=PredictResponse, tags=["Prediction"], summary="Dự đoán Calories")
def predict_calories(request: PredictRequest):
    has_heart_rate = request.heart_rate is not None
    has_body_temp = request.body_temp is not None

    if has_heart_rate and not has_body_temp:
        raise HTTPException(
            status_code=400, 
            detail="Cần cung cấp cả heart_rate và body_temp cùng nhau."
        )
    if not has_heart_rate and has_body_temp:
        raise HTTPException(
            status_code=400, 
            detail="Cần cung cấp cả heart_rate và body_temp cùng nhau."
        )
    
    try:
        sex_val = int(label_encoder.transform([request.sex]))

        if has_heart_rate and has_body_temp:
            input_features = pd.DataFrame([{
                "Sex": sex_val,
                "Age": request.age,
                "Height": request.height,
                "Weight": request.weight,
                "Duration": request.duration,
                "Heart_Rate": request.heart_rate,
                "Body_Temp": request.body_temp
            }])
            prediction = model_7.predict(input_features)
            model_used = "7_features"
            confidence = "high"
        else:
            input_features = pd.DataFrame([{
                "Sex": sex_val,
                "Age": request.age,
                "Height": request.height,
                "Weight": request.weight,
                "Duration": request.duration
            }])
            prediction = model_5.predict(input_features)
            model_used = "5_features"
            confidence = "medium"

        return PredictResponse(
            calories_predicted=round(float(prediction[0]), 2),
            model_used=model_used,
            confidence=confidence
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Dữ liệu đầu vào không hợp lệ: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi từ máy chủ: {str(e)}")

@app.post("/predictions/save", response_model=SavePredictionResponse, tags=["History"], summary="Lưu kết quả Prediction")
def save_prediction(
    request: SavePredictionRequest,
    user_id: str = Depends(get_current_user)
):
    now = datetime.now(timezone.utc)
    evaluation_date = now + timedelta(days=7)
 
    try:
        result = supabase.table("predictions").insert({
            "user_id": user_id,
            "predicted_calories": int(request.predicted_calories),
            "features_used": request.features_used,
            "evaluation_date": evaluation_date.isoformat(),
            "timestamp": now.isoformat(),
            "status": "pending"
        }).execute()
 
        return SavePredictionResponse(
            prediction_id=result.data[0]["id"],
            evaluation_date=evaluation_date.isoformat(),
            message="Đã lưu dự đoán thành công."
        )
 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không lưu được dự đoán: {str(e)}")

@app.get("/predictions/history", response_model=GetHistoryResponse, tags=["History"], summary="Lấy lịch sử Predictions")
def get_history(user_id: str = Depends(get_current_user)):
    try:
        result = supabase.table("predictions") \
            .select("id, predicted_calories, actual_weight_change, features_used, status, timestamp, evaluation_date") \
            .eq("user_id", user_id) \
            .order("timestamp", desc=True) \
            .execute()
 
        return GetHistoryResponse(
            user_id=user_id,
            total=len(result.data),
            predictions=[PredictionHistoryItem(**item) for item in result.data]
        )
 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không nạp được lịch sử: {str(e)}")