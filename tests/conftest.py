"""Shared test fixtures for Oshkelosh tests."""

import os

# Disable auth rate limits for most tests (dedicated tests enable explicitly).
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.core.security import hash_password
from app.db.connection import get_session
from app.main import app
from models.category import Category
from models.product import Product
from models.user import User


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create a fresh async in-memory SQLite session for each test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """Test HTTP client with overridden async DB session dependency."""

    async def override_session():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_session] = override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(db_session) -> User:
    """Create a test admin user."""
    user = User(
        email="test@example.com",
        password_hash=hash_password("SecurePass123!"),
        full_name="Test User",
        is_admin=True,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_product(db_session, test_user: User) -> Product:
    """Create a test product."""
    product = Product(
        name="Test Product",
        description="A test product",
        price_cents=1999,
        sku="TEST-001",
        inventory_quantity=100,
        status="published",
        category="Test Category",
        created_by=test_user.id,
    )
    db_session.add(product)
    await db_session.flush()
    await db_session.refresh(product)
    return product


@pytest_asyncio.fixture
async def test_category(db_session) -> Category:
    """Create a test category."""
    category = Category(
        name="Test Category",
        slug="test-category",
        description="A test category",
    )
    db_session.add(category)
    await db_session.flush()
    await db_session.refresh(category)
    return category
