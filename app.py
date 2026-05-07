from typing import Optional, Literal, List
from fastapi import FastAPI, HTTPException, Header, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timedelta, timezone
import joblib
import pandas as pd
import time
import os
from supabase import create_client, Client
from dotenv import load_dotenv
import jwt
from jwt import PyJWKClient

load_dotenv()

# =====================
# SUPABASE CLIENT
# =====================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not all([SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY]):
    raise RuntimeError("Thiếu biến môi trường Supabase. Vui lòng kiểm tra tệp .env.")

SUPABASE_JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# =====================
# SWAGGER / FASTAPI METADATA
# =====================
description = """
## Calories Prediction API
 
Dự đoán lượng calories tiêu thụ trong quá trình tập luyện dựa trên thông số sinh lý người dùng.
 
### Endpoints
 
| Endpoint | Auth | Mô tả |
|---|---|---|
| `GET /` | Không | Kiểm tra API còn sống không |
| `POST /predict/calories` | Không | Dự đoán calories |
| `POST /predictions/save` | Bearer Token | Lưu kết quả prediction |
| `GET /predictions/history` | Bearer Token | Xem lịch sử predictions |
 
### Models
- **5 features:** sex, age, height, weight, duration -> confidence: **medium**
- **7 features:** 5 features + heart_rate, body_temp -> confidence: **high**
 
### Authentication
Các endpoint có Auth yêu cầu JWT token từ Supabase Auth.
Click nút **Authorize** bên dưới -> nhập token vào ô Value (không cần gõ "Bearer").
"""

app = FastAPI(
    title="Calories Prediction API",
    description=description,
    version="2.0.0",
    openapi_tags=[
        {"name": "Health", "description": "Kiểm tra trạng thái API và models đã sẵn sàng chưa."},
        {"name": "Prediction", "description": "Dự đoán calories từ XGBoost model."},
        {"name": "History", "description": "Lưu và xem lịch sử predictions. Yêu cầu xác thực."}
    ]
)

# =====================
# SECURITY SCHEME
# =====================
bearer_scheme = HTTPBearer(
    scheme_name="Supabase JWT",
    description="Nhập access_token từ Supabase Auth."
)

# =====================
# LOAD MODELS
# =====================
try:
    model_7 = joblib.load("models/xgb_calories_7feat.joblib")
    model_5 = joblib.load("models/xgb_calories_5feat.joblib")
    label_encoder = joblib.load("models/label_encoder_sex.joblib")
except FileNotFoundError as e:
    raise RuntimeError(f"Không tìm thấy tệp mô hình quan trọng: {e}")
except Exception as e:
    raise RuntimeError(f"Lỗi khi tải mô hình: {e}")

# =====================
# AUTH HELPER
# =====================
def get_user_id_from_token(authorization: str) -> str:
    """
    Giải mã JWT từ Supabase Auth.
    Header format: "Bearer <token>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header thiếu hoặc không hợp lệ.")
    
    token = authorization.split(" ")[1]

    try:
        jwks_client = PyJWKClient(SUPABASE_JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token, 
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token Không hợp lệ: Thiếu user ID.")
        return user_id
    
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token đã hết hạn.")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Token không hợp lệ: {str(e)}")

# =====================
# SCHEMAS
# =====================
class PredictRequest(BaseModel):
    sex: Literal["male", "female"] = Field(..., description="Giới tính", example=["male"])
    age: float = Field(..., gt=0, lt=120, description="Tuổi", example=[30])
    height: float = Field(..., gt=0, lt=300, description="Chiều cao (cm)", example=[175.0])
    weight: float = Field(..., gt=0, lt=300, description="Cân nặng (kg)", example=[70.0])
    duration: float = Field(..., gt=0, description="Thời gian tập luyện (phút)", example=[30])
    heart_rate: Optional[float] = Field(None, gt=0, lt=250, description="Nhịp tim (bpm) - tùy chọn, bắt buộc đi kèm body_temp", example=[12.0])
    body_temp: Optional[float] = Field(None, gt=35.0, lt=42.0, description="Nhiệt độ cơ thể (độ C) - tùy chọn, bắt buộc đi kèm heart_rate", example=[37.0])

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "5 features (không có smartwatch)",
                    "value": {"sex": "male", "age": 25, "height": 170.0, "weight": 70.0, "duration": 30.0}
                },
                {
                    "summary": "7 features (có smartwatch)",
                    "value": {"sex": "male", "age": 25, "height": 170.0, "weight": 70.0, "duration": 30.0, "heart_rate": 120.0, "body_temp": 37.5}
                }
            ]
        }
    }

class PredictResponse(BaseModel):
    calories_predicted: float = Field(description="Caloriess dự đoán (kcal)")
    model_used: str = Field(description="Model được sử dụng: '5_features' hoặc '7_features'")
    confidence: str = Field(description="Mức độ tin cậy của dự đoán: 'medium' cho 5 features, 'high' cho 7 features")

class SavePredictionRequest(BaseModel):
    predicted_calories: int = Field(..., gt=0, description="Calories từ /predict/calories - tự động làm tròn thành int", example=245.67)
    features_used: Literal[5, 7] = Field(..., description="Số features đã dùng khi predict", example=7)

    @field_validator("predicted_calories", mode="before")
    @classmethod
    def coerce_to_int(cls, v):
        return round(float(v))

class SavePredictionResponse(BaseModel):
    prediction_id: str = Field(description="UUID của prediction vừa lưu vào Supabase")
    evaluation_date: str = Field(description="Ngày đánh giá prediction (timestamp + 7 ngày)")
    message: str = Field(description="Thông báo kết quả lưu prediction")

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
    return {"message": "Calories Prediction API v2.0 is running"}

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

# Endpoint chính để dự đoán calories. Hỗ trợ cả 5 và 7 features tùy theo input.
@app.post(
    "/predict/calories", 
    response_model=PredictResponse,
    tags=["Prediction"],
    summary="Dự đoán Calories",
    description="""
Dự đoán lượng calories tiêu thụ dựa trên thông số sinh lý.
 
**Model tự động chọn:**
- Không có `heart_rate` và `body_temp` -> model 5 features, confidence **medium**
- Có cả `heart_rate` và `body_temp` -> model 7 features, confidence **high**
 
**Lưu ý:** `heart_rate` và `body_temp` phải được cung cấp cùng nhau hoặc bỏ cả hai.
    """,
    responses={
        200: {"description": "Dự đoán thành công"},
        400: {"description": "Dữ liệu đầu vào không hợp lệ"},
        500: {"description": "Lỗi server"}
    }
)
def predict_calories(request: PredictRequest):
    has_heart_rate = request.heart_rate is not None
    has_body_temp = request.body_temp is not None

    if has_heart_rate and not has_body_temp:
        raise HTTPException(
            status_code=400, 
            detail="Dữ liệu nhập không hợp lệ: Đã cung cấp nhịp tim nhưng thiếu nhiệt độ cơ thể. Cả hai đều được yêu cầu cho dữ liệu của đồng hồ thông minh."
        )
    if not has_heart_rate and has_body_temp:
        raise HTTPException(
            status_code=400, 
            detail="Dữ liệu nhập không hợp lệ: Đã cung cấp nhiệt độ cơ thể nhưng thiếu nhịp tim. Cả hai đều được yêu cầu cho dữ liệu của đồng hồ thông minh."
        )
    
    try:
        sex_val = int(label_encoder.transform([request.sex]))

        # Tạo Dataframe
        df_start = time.time()

        if has_heart_rate and has_body_temp:
            # 7 FEATURES
            input_features = pd.DataFrame([{
                "Sex": sex_val,
                "Age": request.age,
                "Height": request.height,
                "Weight": request.weight,
                "Duration": request.duration,
                "Heart_Rate": request.heart_rate,
                "Body_Temp": request.body_temp
            }])

            model_used = "7_features"
            confidence = "high"
        else:
            # 5 FEATURES
            input_features = pd.DataFrame([{
                "Sex": sex_val,
                "Age": request.age,
                "Height": request.height,
                "Weight": request.weight,
                "Duration": request.duration
            }])

            model_used = "5_features"
            confidence = "medium"

        # Model Prediction
        prediction = model_7.predict(input_features) if has_heart_rate and has_body_temp else model_5.predict(input_features)

        # Post_processing
        response_data = PredictResponse(
            calories_predicted=round(float(prediction), 2),
            model_used=model_used,
            confidence=confidence
        )

        return response_data

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Dữ liệu đầu vào không hợp lệ: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi từ máy chủ: {str(e)}")

# Endpoint để lưu kết quả prediction vào Supabase. Gọi sau khi frontend nhận được kết quả từ /predict/calories.
@app.post(
    "/predictions/save", 
    response_model=SavePredictionResponse,
    tags=["History"],
    summary="Lưu kết quả Prediction",
    description="""
Lưu kết quả prediction vào database sau khi user xác nhận.
 
**Yêu cầu:** Bearer token từ Supabase Auth.
 
- `evaluation_date` tự động tính = thời điểm lưu + 7 ngày
- `predicted_calories` nhận float, tự động làm tròn thành int
- `user_id` lấy từ JWT token, không cần truyền trong body
    """,
    responses={
        200: {"description": "Lưu thành công"},
        401: {"description": "Token không hợp lệ hoặc hết hạn"},
        500: {"description": "Lỗi server hoặc database"}
    }
)
def save_prediction(
    request: SavePredictionRequest,
    authorization: str = Header(..., description="Bearer <supabase_jwt_token>")
):
    user_id = get_user_id_from_token(authorization)
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
 
        prediction_id = result.data[0]["id"]
 
        return SavePredictionResponse(
            prediction_id=prediction_id,
            evaluation_date=evaluation_date.isoformat(),
            message="Đã lưu dự đoán thành công."
        )
 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không lưu được dự đoán: {str(e)}")

# Endpoint để lấy lịch sử predictions của user đang đăng nhập. Sắp xếp mới nhất lên đầu.
@app.get(
    "/predictions/history", 
    response_model=GetHistoryResponse,
    tags=["History"],
    summary="Lấy lịch sử Predictions",
    description="""
Lấy toàn bộ lịch sử predictions của user đang đăng nhập.
 
**Yêu cầu:** Bearer token từ Supabase Auth.
 
- Kết quả sắp xếp mới nhất trước
- `actual_weight_change` sẽ là `null` cho đến khi cron job resolve sau 7 ngày
- `status`: `pending` = chưa đánh giá, `resolved` = đã có kết quả thực tế
    """,
    responses={
        200: {"description": "Trả về danh sách predictions"},
        401: {"description": "Token không hợp lệ hoặc hết hạn"},
        500: {"description": "Lỗi server hoặc database"}
    }
)
def get_history(
    authorization: str = Header(..., description="Bearer <supabase_jwt_token>")
):
    user_id = get_user_id_from_token(authorization)
 
    try:
        result = supabase.table("predictions") \
            .select("id, predicted_calories, actual_weight_change, features_used, status, timestamp, evaluation_date") \
            .eq("user_id", user_id) \
            .order("timestamp", desc=True) \
            .execute()
 
        predictions = [PredictionHistoryItem(**item) for item in result.data]
 
        return GetHistoryResponse(
            user_id=user_id,
            total=len(predictions),
            predictions=predictions
        )
 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Không nạp được lịch sử: {str(e)}")