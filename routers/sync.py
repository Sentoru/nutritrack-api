"""
POST /sync/health-data — Nhận dữ liệu từ Health Connect (Android)
"""

from typing import Optional
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from auth import get_current_user
from database import supabase

router = APIRouter(prefix="/sync", tags=["Health Data Sync"])

# -- Schemas -------------------------------------------------------------------- 

class HealthSyncRequest(BaseModel):
    steps: Optional[int] = Field(None, ge=0, description="Số bước chân trong ngày")
    heart_rate: Optional[float] = Field(None, gt=0, lt=250, description="Nhịp tim trung bình (bpm)")
    body_temp: Optional[float] = Field(None, gt=35.0, lt=42.0, description="Nhiệt độ cơ thể (°C)")
    sync_date: Optional[date] = Field(None, description="YYYY-MM-DD, mặc định hôm nay")

class HealthSyncResponse(BaseModel):
    sync_id: str
    user_id: str
    sync_date: str
    steps: Optional[int]
    heart_rate: Optional[float]
    body_temp: Optional[float]
    synced_at: str

# -- Endpoints ------------------------------------------------------------------

@router.post(
    "/health-data",
    response_model=HealthSyncResponse,
    summary="Đồng bộ dữ liệu từ Health Connect",
    description="""
Nhận dữ liệu sức khỏe từ Health Connect (Android) gửi lên.

- Nếu đồng bộ nhiều lần trong ngày: **chỉ giữ giá trị mới nhất** (UPSERT theo user_id + sync_date).
- `steps`, `heart_rate`, `body_temp` đều optional — gửi cái nào có cái đó.
- `heart_rate` và `body_temp` sẽ được dùng làm input cho ML model (7 features) khi predict calories.
    """,
)
def sync_health_data(body: HealthSyncRequest, user_id: str = Depends(get_current_user)):
    if not any([body.steps is not None, body.heart_rate, body.body_temp]):
        raise HTTPException(status_code=400, detail="Cần ít nhất một trường dữ liệu: steps, heart_rate, hoặc body_temp.")

    sync_date = str(body.sync_date or date.today())
    now = datetime.now(timezone.utc).isoformat()

    data = {
        "user_id":   user_id,
        "sync_date": sync_date,
        "synced_at": now,
    }
    if body.steps is not None:
        data["steps"] = body.steps
    if body.heart_rate is not None:
        data["heart_rate"] = body.heart_rate
    if body.body_temp is not None:
        data["body_temp"] = body.body_temp

    # UPSERT — tránh cộng dồn sai khi sync nhiều lần trong ngày
    result = supabase.table("health_data_sync").upsert(
        data, on_conflict="user_id,sync_date"
    ).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Đồng bộ thất bại.")
    return result.data[0]