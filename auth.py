"""
JWT verification dùng Supabase JWKS.
PyJWKClient được cache ở module level — chỉ fetch JWKS 1 lần,
tránh gọi network mỗi request.
"""

import os
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"

bearer_scheme = HTTPBearer(
    scheme_name="Supabase JWT",
    description="Nhập access_token từ Supabase.",
)

# Cache JWKS client ở module level
_jwks_client = PyJWKClient(SUPABASE_JWKS_URL, cache_keys=True)

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme),) -> str:
    """
    Verify Supabase JWT, trả về user_id (sub).
    Dùng làm dependency: user_id: str = Depends(get_current_user)
    """
    token = credentials.credentials
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token, 
            signing_key.key, 
            algorithms=["ES256"], 
            audience="authenticated",
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token không hợp lệ: thiếu user ID.")
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token đã hết hạn.")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Token không hợp lệ: {str(e)}")