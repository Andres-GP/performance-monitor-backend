import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    WEBSOCKET_PORT: int = 9001
    API_PORT: int = 8000

    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

    API_SECRET_KEY: str = os.getenv("API_SECRET_KEY", "changeme")

settings = Settings()