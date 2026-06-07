"""
Test fixtures using an in-memory SQLite database so tests run without Postgres.
SQLite doesn't support schemas, so model tables are patched to use no schema,
and Enum types are made non-native (VARCHAR) before table creation.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Import models so they register with Base.metadata
import app.identity.models  # noqa: F401
import app.scheduling.models  # noqa: F401
from app.auth.router import hash_password
from app.database import Base, get_session
from app.main import app as fastapi_app  # renamed to avoid shadowing by 'app' package
from app.scheduling.models import StaffRole, StaffUser

DATABASE_URL = "sqlite+aiosqlite:///:memory:"


def _strip_schemas(metadata):
    """Remove PostgreSQL schemas from all tables so SQLite can create them."""
    for table in metadata.tables.values():
        table.schema = None
    # Also patch any schema-qualified Enum types to native_enum=False
    for table in metadata.tables.values():
        for col in table.columns:
            t = col.type
            if hasattr(t, "schema"):
                t.schema = None
            if hasattr(t, "native_enum"):
                t.native_enum = False


@pytest_asyncio.fixture(scope="function")
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(DATABASE_URL, echo=False)
    _strip_schemas(Base.metadata)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_session():
        yield session

    fastapi_app.dependency_overrides[get_session] = override_session
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as c:
        yield c
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def admin_user(session: AsyncSession) -> StaffUser:
    user = StaffUser(
        id=uuid.uuid4(),
        username="testadmin",
        hashed_password=hash_password("testpass"),
        role=StaffRole.admin,
    )
    session.add(user)
    await session.commit()
    return user


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient, admin_user: StaffUser) -> dict:
    resp = await client.post("/auth/login", json={"username": "testadmin", "password": "testpass"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
