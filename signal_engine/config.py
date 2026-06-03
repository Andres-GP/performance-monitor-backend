import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    # Server
    HOST: str = "0.0.0.0"
    WEBSOCKET_PORT: int = 9001
    API_PORT: int = 8000
    
    # Security
    API_SECRET_KEY: str = "changeme"
    JWT_ALGORITHM: str = "HS256"
    
    # Database
    DATABASE_URL: str = "sqlite:///./signal_engine.db"
    
    # Risk limits
    MAX_DAILY_DRAWDOWN_PERCENT: float = 2.0
    MAX_POSITION_SIZE: float = 0.1
    MAX_ORDERS_PER_MINUTE: int = 10
    
    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()