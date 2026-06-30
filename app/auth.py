import os
from fastapi import HTTPException, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from clerk_backend_api import Clerk
from clerk_backend_api.models import ClerkErrors, SDKError
from .config import settings

security = HTTPBearer()

clerk_client = None
if settings.CLERK_SECRET_KEY:
    clerk_client = Clerk(bearer_auth=settings.CLERK_SECRET_KEY)
else:
    print("CLERK_SECRET_KEY not set. Clerk authentication disabled.")

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    if clerk_client:
        try:
            return {"user_id": "clerk_user", "auth_type": "clerk"}
        except Exception as e:
            print(f"Clerk validation failed: {e}")
            # Si falla, continuar con el siguiente método
            pass

    if token == settings.API_SECRET_KEY:
        return {"user_id": "api_key_user", "auth_type": "api_key"}

    raise HTTPException(status_code=401, detail="Invalid authentication credentials")