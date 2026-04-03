from urllib.parse import urlencode

from orders.core.settings import settings


def build_mysql_sync_url() -> str:
    query = urlencode({"init_command": "SET time_zone = '+00:00'"})
    return (
        f"mysql+pymysql://{settings.mysql_user}:{settings.mysql_pass}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
        f"?{query}"
    )
