from typing import Optional, Literal, List
from fastapi import FastAPI, HTTPException, Header
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
SUPABASE_JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"

if not all([SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY]):
    raise RuntimeError("Missing Supabase environment variables. Please check .env file.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# =====================
# LOAD MODELS
# =====================
app = FastAPI(title="Calories Prediction API v.2.0")
try:
    model_7 = joblib.load("models/xgb_calories_7feat.joblib")
    model_5 = joblib.load("models/xgb_calories_5feat.joblib")
    label_encoder = joblib.load("models/label_encoder_sex.joblib")
except FileNotFoundError as e:
    raise RuntimeError(f"Important model file not found: {e}")
except Exception as e:
    raise RuntimeError(f"Error when loading model: {e}")

# =====================
# AUTH HELPER
# =====================
def get_user_id_from_token(authorization: str) -> str:
    """
    Decoding JWT from Supabase Auth.
    Header format: "Bearer <token>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    
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
            raise HTTPException(status_code=401, detail="Invalid token: Missing user ID.")
        return user_id
    
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired.")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

# =====================
# SCHEMAS
# =====================
class PredictRequest(BaseModel):
    sex: Literal["male", "female"] = Field(..., description="Sex: 'male' or 'female'")
    age: float = Field(..., gt=0, lt=120, description="Age")
    height: float = Field(..., gt=0, lt=300, description="Height (cm)")
    weight: float = Field(..., gt=0, lt=300, description="Weight (kg)")
    duration: float = Field(..., gt=0, description="Time (minutes)")
    heart_rate: Optional[float] = Field(None, gt=0, lt=250, description="Heart rate (bpm)")
    body_temp: Optional[float] = Field(None, gt=35.0, lt=42.0, description="Body temperature (C)")

class PredictResponse(BaseModel):
    calories_predicted: float
    model_used: str
    confidence: str # "high" or "medium"

class SavePredictionRequest(BaseModel):
    predicted_calories: int = Field(..., gt=0, description="Predicted calories from model (float, will be rounded to int)")
    features_used: Literal[5, 7] = Field(..., description="Number of features used: 5 or 7")

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
    return {"message": "Calories Prediction API is running"}

# Endpoint chính để dự đoán calories. Hỗ trợ cả 5 và 7 features tùy theo input.
@app.post("/predict/calories", response_model=PredictResponse)
def predict_calories(request: PredictRequest):
    has_heart_rate = request.heart_rate is not None
    has_body_temp = request.body_temp is not None

    if has_heart_rate and not has_body_temp:
        raise HTTPException(
            status_code=400, 
            detail="Invalid input: Heart rate provided but body temperature is missing. Both are required for smartwatch data."
        )
    if not has_heart_rate and has_body_temp:
        raise HTTPException(
            status_code=400, 
            detail="Invalid input: Body temperature provided but heart rate is missing. Both are required for smartwatch data."
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
        raise HTTPException(status_code=400, detail=f"Invalid data input: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error from server: {str(e)}")

# Endpoint để lưu kết quả prediction vào Supabase. Gọi sau khi frontend nhận được kết quả từ /predict/calories.
@app.post("/predictions/save", response_model=SavePredictionResponse)
def save_prediction(
    request: SavePredictionRequest,
    authorization: str = Header(..., description="Bearer <supabase_jwt_token>")
):
    """
    Lưu kết quả prediction vào Supabase.
    Frontend gọi sau khi nhận được kết quả từ /predict/calories.
    evaluation_date = timestamp + 7 ngày.
    """
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
            message="Prediction saved successfully."
        )
 
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save prediction: {str(e)}")

# Endpoint để lấy lịch sử predictions của user đang đăng nhập. Sắp xếp mới nhất lên đầu.
@app.get("/predictions/history", response_model=GetHistoryResponse)
def get_history(
    authorization: str = Header(..., description="Bearer <supabase_jwt_token>")
):
    """
    Lấy toàn bộ lịch sử predictions của user đang đăng nhập.
    Sắp xếp mới nhất lên đầu.
    """
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
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {str(e)}")