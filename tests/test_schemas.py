"""Tests for Pydantic schemas."""

from decimal import Decimal
import pytest
from pydantic import ValidationError

from schemas.user import UserCreate, UserRead, UserRegister
from schemas.product import ProductCreate, ProductRead
from schemas.category import CategoryCreate
from schemas.base import PaginatedResponse, MessageResponse


class TestUserRegister:
    """Test UserRegister schema."""

    def test_valid_registration(self):
        user = UserRegister(
            email="user@example.com",
            password="SecurePass123!",
            full_name="Test User",
        )
        assert user.email == "user@example.com"
        assert user.full_name == "Test User"

    def test_extra_privilege_fields_ignored(self):
        user = UserRegister.model_validate(
            {
                "email": "user@example.com",
                "password": "SecurePass123!",
                "full_name": "Test",
                "is_admin": True,
            }
        )
        assert not hasattr(user, "is_admin") or getattr(user, "is_admin", None) is not True


class TestUserCreate:
    """Test admin UserCreate schema."""

    def test_admin_create_includes_flags(self):
        user = UserCreate(
            email="admin@example.com",
            password="SecurePass123!",
            full_name="Admin",
            is_admin=True,
        )
        assert user.is_admin is True

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            UserCreate(
                email="not-an-email",
                password="SecurePass123!",
                full_name="Test",
            )

    def test_short_password(self):
        with pytest.raises(ValidationError):
            UserCreate(
                email="user@example.com",
                password="short",
                full_name="Test",
            )


class TestProductSchema:
    """Test product schemas."""

    def test_valid_product_create(self):
        product = ProductCreate(
            name="Test Product",
            price_cents=1999,
        )
        assert product.name == "Test Product"
        assert product.price_cents == 1999

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            ProductCreate(name="Bad", price_cents=-1)

    def test_price_decimal_conversion(self):
        product = ProductRead.model_validate({
            "id": 1,
            "name": "Test",
            "description": None,
            "price_cents": 1999,
            "compare_at_price_cents": None,
            "sku": "TEST-001",
            "inventory_quantity": 10,
            "status": "published",
            "category_id": None,
            "tags": [],
            "images": [],
            "created_by": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        })
        assert product.price == Decimal("19.99")
        assert product.compare_at_price is None


class TestPaginatedResponse:
    """Test generic pagination schema."""

    def test_paginated_response(self):
        resp = PaginatedResponse(
            items=[1, 2, 3],
            page=1,
            page_size=10,
            total=25,
            total_pages=3,
        )
        assert resp.items == [1, 2, 3]
        assert resp.total == 25
        assert resp.total_pages == 3


class TestMessageResponse:
    """Test message response schema."""

    def test_message_response(self):
        msg = MessageResponse(message="Hello")
        assert msg.message == "Hello"
