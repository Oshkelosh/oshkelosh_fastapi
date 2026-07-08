"""Shared test fixtures for Oshkelosh tests."""

import os

# Disable auth rate limits for most tests (dedicated tests enable explicitly).
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("REQUIRE_EMAIL_VERIFICATION", "false")

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.core.security import hash_password
from app.db.sqlite_utils import configure_sqlite_foreign_keys
from app.db.connection import get_session
from app.main import app
from models.category import Category
from models.product import Product
from models.product_variant import ProductVariant
from models.user import User
from app.services.product_variants import create_default_variant, refresh_product_listing_cache
import models.manual_supplier  # noqa: F401 — register table for tests
import models.notification_template  # noqa: F401 — register table for tests
import models.audit_log  # noqa: F401 — register table for tests
import models.order_idempotency_key  # noqa: F401 — register table for tests
import models.product_variant  # noqa: F401 — register table for tests


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
    configure_sqlite_foreign_keys(engine)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    from pathlib import Path
    from sqlalchemy import text

    migration_path = (
        Path(__file__).resolve().parents[1] / "migrations" / "d1" / "000_initial.sql"
    )
    if migration_path.exists():
        raw = migration_path.read_text()
        async with engine.begin() as conn:
            for statement in raw.split(";"):
                stmt = statement.strip()
                if not stmt or stmt.startswith("--"):
                    continue
                await conn.execute(text(stmt))

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))
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
        verified=True,
        banned=False,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_product(db_session, test_user: User, test_category: Category) -> Product:
    """Create a test product."""
    product = Product(
        name="Test Product",
        slug="test-product",
        description="A test product",
        price_cents=1999,
        sku="TEST-001",
        inventory_quantity=100,
        status="published",
        category_id=test_category.id,
        created_by=test_user.id,
    )
    db_session.add(product)
    await db_session.flush()
    variant = ProductVariant(
        product_id=product.id,
        title=product.name,
        position=0,
        price_cents=product.price_cents,
        inventory_quantity=product.inventory_quantity,
        sku=product.sku,
        status="active",
    )
    db_session.add(variant)
    await db_session.flush()
    refresh_product_listing_cache(product, [variant])
    await db_session.refresh(product)
    await db_session.refresh(variant)
    product._test_variant = variant  # type: ignore[attr-defined]
    return product


@pytest.fixture
def test_variant(test_product: Product) -> ProductVariant:
    """Default variant for test_product."""
    return test_product._test_variant  # type: ignore[attr-defined]


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
