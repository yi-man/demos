from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from orders.core.settings import settings


def build_mysql_async_url() -> str:
    return (
        f"mysql+aiomysql://{settings.mysql_user}:{settings.mysql_pass}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_database}"
    )


async_engine = create_async_engine(build_mysql_async_url(), pool_pre_ping=True)

SessionMaker = async_sessionmaker(
    async_engine,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionMaker() as session:
        yield session
