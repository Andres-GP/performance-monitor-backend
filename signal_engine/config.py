import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv() 

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    WEBSOCKET_PORT: int = 9001
    API_PORT: int = 8000
    
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    
    API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "changeme")
    JWT_ALGORITHM: str = "HS256"
    
    MAX_DAILY_DRAWDOWN_PERCENT: float = 2.0
    MAX_POSITION_SIZE: float = 0.1
    MAX_ORDERS_PER_MINUTE: int = 10

settings = Settings()

# Debug: imprime primeros caracteres para verificar (comentar después)
print(f"SUPABASE_URL: {settings.SUPABASE_URL[:20]}...")
print(f"SUPABASE_KEY starts with: {settings.SUPABASE_SERVICE_ROLE_KEY[:10]}...")