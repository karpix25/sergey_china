import os
from fastapi import HTTPException, Security, status, Request
from fastapi.security.api_key import APIKeyHeader

API_KEY_NAME = "X-Internal-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def get_api_key(request: Request, api_key_h: str = Security(api_key_header)):
    expected_key = os.getenv("INTERNAL_API_KEY")
    if not expected_key:
        return None 
    
    # Check header first, then query param
    api_key = api_key_h or request.query_params.get("api_key")
    if api_key == expected_key:
        return api_key
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
    )
