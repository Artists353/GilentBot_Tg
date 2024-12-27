import os

from sqlalchemy.ext.asyncio import (AsyncEngine, AsyncSession,
                                    async_sessionmaker, create_async_engine)

db_path = os.path.join(
    os.path.dirname(os.path.abspath(__package__)),
    "database.sqlite3",
)

engine: AsyncEngine = create_async_engine(url=f"sqlite+aiosqlite:///{db_path}", echo=True)
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False
)
