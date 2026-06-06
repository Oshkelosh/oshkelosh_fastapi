"""Oshkelosh Pydantic v2 schemas.

Exports every request/response schema so consumers can do
``from schemas import UserRead, ProductCreate, PaginatedResponse`` etc.
"""

from schemas.base import MessageResponse, PaginatedResponse
from schemas.user import Token, UserCreate, UserLogin, UserRead, UserRegister, UserUpdate
from schemas.product import ProductCreate, ProductImageCreate, ProductRead, ProductUpdate
from schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from schemas.cart import (
    CartCreate,
    CartItemAdd,
    CartItemRead,
    CartItemUpdate,
    CartRead,
)
from schemas.order import OrderCreate, OrderItemRead, OrderRead, OrderUpdateStatus

__all__ = [
    # base
    "PaginatedResponse",
    "MessageResponse",
    # user
    "UserCreate",
    "UserRegister",
    "UserUpdate",
    "UserRead",
    "UserLogin",
    "Token",
    # product
    "ProductCreate",
    "ProductUpdate",
    "ProductRead",
    "ProductImageCreate",
    # category
    "CategoryCreate",
    "CategoryUpdate",
    "CategoryRead",
    # cart
    "CartCreate",
    "CartItemAdd",
    "CartItemUpdate",
    "CartRead",
    "CartItemRead",
    # order
    "OrderCreate",
    "OrderRead",
    "OrderItemRead",
    "OrderUpdateStatus",
]
