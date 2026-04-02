from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Keep existing defaults for the app (used by /healthz debug).
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 9600

    # MySQL connection pieces (use exact env names provided by user).
    mysql_host: str = Field(default="127.0.0.1", validation_alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, validation_alias="MYSQL_PORT")
    mysql_user: str = Field(default="root", validation_alias="MYSQL_USER")
    mysql_pass: str = Field(default="", validation_alias="MYSQL_PASS")
    mysql_database: str = Field(default="superman", validation_alias="MYSQL_DATABASE")

    # Redis connection URL.
    redis_url: str = Field(
        default="redis://127.0.0.1:6379",
        validation_alias="REDIS_URL",
    )

    model_config = SettingsConfigDict(env_prefix="ORDERS_", extra="ignore")


settings = Settings()
