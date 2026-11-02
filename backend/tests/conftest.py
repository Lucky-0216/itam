import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_itam.db"
os.environ["TOKEN_STORE"] = "memory"
os.environ["SECRET_KEY"] = "test-secret-key-for-itam-only-0123456789abc"
os.environ["DEFAULT_ADMIN_USERNAME"] = "admin"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "Test@12345"
os.environ["DEFAULT_USER_PASSWORD"] = "Test@12345"
os.environ["UPLOAD_DIR"] = "./test_uploads"
os.environ["SEED_SAMPLE_DATA"] = "true"

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.core.token_store import reset_token_store  # noqa: E402
from app.initial_data import seed_initial_data  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402


@pytest_asyncio.fixture
async def client():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await seed_initial_data(session)

    reset_token_store()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
