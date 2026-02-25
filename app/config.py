from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False)

    canvas_base_url: str = Field(default="", alias="CANVAS_BASE_URL")
    canvas_token: str = Field(default="", alias="CANVAS_TOKEN")

    ms_tenant_id: str = Field(default="", alias="MS_TENANT_ID")
    ms_client_id: str = Field(default="", alias="MS_CLIENT_ID")
    ms_client_secret: str = Field(default="", alias="MS_CLIENT_SECRET")
    ms_user_email: str = Field(default="", alias="MS_USER_EMAIL")

    push_provider: str = Field(default="pushover", alias="PUSH_PROVIDER")
    pushover_app_token: str = Field(default="", alias="PUSHOVER_APP_TOKEN")
    pushover_user_key: str = Field(default="", alias="PUSHOVER_USER_KEY")

    schedule_time: str = Field(default="07:30", alias="SCHEDULE_TIME")
    timezone: str = Field(default="America/Los_Angeles", alias="TIMEZONE")

    digest_lookahead_days: int = Field(default=3, alias="DIGEST_LOOKAHEAD_DAYS")
    important_keywords: str = Field(default="urgent,important,deadline,exam,quiz,project", alias="IMPORTANT_KEYWORDS")


settings = Settings()
