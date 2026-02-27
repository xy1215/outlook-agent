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
    ms_redirect_uri: str = Field(default="http://127.0.0.1:8000/auth/callback", alias="MS_REDIRECT_URI")
    ms_token_store_path: str = Field(default="data/ms_token.json", alias="MS_TOKEN_STORE_PATH")

    push_provider: str = Field(default="pushover", alias="PUSH_PROVIDER")
    pushover_app_token: str = Field(default="", alias="PUSHOVER_APP_TOKEN")
    pushover_user_key: str = Field(default="", alias="PUSHOVER_USER_KEY")

    schedule_time: str = Field(default="07:30", alias="SCHEDULE_TIME")
    timezone: str = Field(default="America/Los_Angeles", alias="TIMEZONE")

    digest_lookahead_days: int = Field(default=3, alias="DIGEST_LOOKAHEAD_DAYS")
    important_keywords: str = Field(default="urgent,important,deadline,exam,quiz,project", alias="IMPORTANT_KEYWORDS")
    task_mode: str = Field(default="action_only", alias="TASK_MODE")
    task_action_keywords: str = Field(
        default="due,deadline,exam,quiz,submission,assignment,homework,hw,project,midterm,final,participation,lab",
        alias="TASK_ACTION_KEYWORDS",
    )
    task_noise_keywords: str = Field(
        default="assignment graded,graded:,office hours moved,daily digest,announcement posted",
        alias="TASK_NOISE_KEYWORDS",
    )
    task_require_due: bool = Field(default=True, alias="TASK_REQUIRE_DUE")
    push_due_within_hours: int = Field(default=48, alias="PUSH_DUE_WITHIN_HOURS")

    llm_enabled: bool = Field(default=False, alias="LLM_ENABLED")
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    llm_timeout_sec: int = Field(default=20, alias="LLM_TIMEOUT_SEC")
    llm_max_mails: int = Field(default=8, alias="LLM_MAX_MAILS")


settings = Settings()
