from orders.core.settings import settings


def build_mysql_sync_url() -> str:
    return (
        f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_pass}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
    )

