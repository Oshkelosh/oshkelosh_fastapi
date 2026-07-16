"""Oshkelosh Pydantic v2 schemas.

Exports every request/response schema so consumers can do
``from schemas import UserRead, ProductCreate, PaginatedResponse`` etc.
"""

from schemas.base import MessageResponse, PaginatedResponse
from schemas.user import (
    Token,
    UserCreate,
    UserLogin,
    UserProfileUpdate,
    UserRead,
    UserRegister,
    UserUpdate,
    EmailVerifyRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    RegisterResponse,
)
from schemas.address import Address
from schemas.product import ProductCreate, ProductImageCreate, ProductRead, ProductUpdate
from schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from schemas.cart import (
    CartItemAdd,
    CartItemRead,
    CartItemUpdate,
    CartRead,
)
from schemas.order import (
    OrderCheckoutUpdate,
    OrderCreateFromCart,
    OrderItemRead,
    OrderRead,
    OrderUpdateStatus,
)
from schemas.payment import PaymentWebhookOutcome

__all__ = [
    # base
    "PaginatedResponse",
    "MessageResponse",
    # user
    "UserCreate",
    "UserRegister",
    "UserUpdate",
    "UserProfileUpdate",
    "EmailVerifyRequest",
    "ForgotPasswordRequest",
    "ResetPasswordRequest",
    "UserRead",
    "UserLogin",
    "Token",
    "RegisterResponse",
    "Address",
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
    "CartItemAdd",
    "CartItemUpdate",
    "CartRead",
    "CartItemRead",
    # order
    "OrderCreateFromCart",
    "OrderCheckoutUpdate",
    "OrderRead",
    "OrderItemRead",
    "OrderUpdateStatus",
    # payment
    "PaymentWebhookOutcome",
]
