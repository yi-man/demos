from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 9600

    model_config = SettingsConfigDict(env_prefix="ORDERS_", extra="ignore")


settings = Settings()
