from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://smartslot:smartslot@localhost:5432/smartslot"
    app_secret: str = "local-demo-secret-change-me"
    business_timezone: str = "Asia/Kolkata"
    tomtom_routing_api_key: str = ""
    allow_insecure_demo_login: bool = False
    allow_insecure_demo_admin: bool = False
    notification_webhook_url: str = ""
    notification_webhook_secret: str = ""
    auto_allocator_enabled: bool = True
    auto_allocator_interval_seconds: int = 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
