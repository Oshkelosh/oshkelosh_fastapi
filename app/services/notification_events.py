"""Notification event catalog — stable keys, channels, placeholders, defaults."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

NotificationChannel = Literal["email", "sms", "push"]

EVENT_GROUP_ORDERS = "orders"
EVENT_GROUP_ACCOUNT = "account"
EVENT_GROUP_MARKETING = "marketing"


@dataclass(frozen=True)
class NotificationEventDef:
    key: str
    label: str
    group: str
    description: str
    channels: tuple[NotificationChannel, ...]
    placeholders: tuple[str, ...]
    default_subject: str
    default_body: str


NOTIFICATION_EVENTS: dict[str, NotificationEventDef] = {
    "order_placed": NotificationEventDef(
        key="order_placed",
        label="Order placed",
        group=EVENT_GROUP_ORDERS,
        description="Sent when a customer places an order (pending checkout).",
        channels=("email", "sms", "push"),
        placeholders=("order_id", "store_name", "customer_name", "total_cents"),
        default_subject="We received your order",
        default_body=(
            "Thank you, {customer_name}! We received order #{order_id}. "
            "Complete payment to confirm your purchase."
        ),
    ),
    "order_confirmation": NotificationEventDef(
        key="order_confirmation",
        label="Order confirmation",
        group=EVENT_GROUP_ORDERS,
        description="Sent when payment is received (pending → paid).",
        channels=("email", "sms", "push"),
        placeholders=("order_id", "store_name", "customer_name"),
        default_subject="Order confirmation",
        default_body=(
            "Thank you for your order #{order_id}. Your payment was received."
        ),
    ),
    "order_shipped": NotificationEventDef(
        key="order_shipped",
        label="Order shipped",
        group=EVENT_GROUP_ORDERS,
        description="Sent when the order ships (paid → shipped).",
        channels=("email", "sms", "push"),
        placeholders=("order_id", "store_name", "tracking_url", "tracking_number", "carrier"),
        default_subject="Your order has shipped",
        default_body="Order #{order_id} is on its way.",
    ),
    "order_delivered": NotificationEventDef(
        key="order_delivered",
        label="Order delivered",
        group=EVENT_GROUP_ORDERS,
        description="Sent when the order is delivered (shipped → delivered).",
        channels=("email", "sms", "push"),
        placeholders=("order_id", "store_name"),
        default_subject="Order delivered",
        default_body=(
            "Order #{order_id} has been delivered. Thank you for shopping with us!"
        ),
    ),
    "email_verification": NotificationEventDef(
        key="email_verification",
        label="Email verification",
        group=EVENT_GROUP_ACCOUNT,
        description="Sent when a user registers or requests a new verification link.",
        channels=("email",),
        placeholders=("verify_url", "store_name", "expire_hours"),
        default_subject="Verify your account",
        default_body=(
            "Please verify your email address by opening this link:\n\n"
            "{verify_url}\n\n"
            "This link expires in {expire_hours} hours."
        ),
    ),
    "password_reset": NotificationEventDef(
        key="password_reset",
        label="Password reset",
        group=EVENT_GROUP_ACCOUNT,
        description="Sent when a user requests a password reset.",
        channels=("email",),
        placeholders=("reset_url", "store_name", "expire_hours"),
        default_subject="Reset your password",
        default_body=(
            "Reset your password by opening this link:\n\n"
            "{reset_url}\n\n"
            "This link expires in {expire_hours} hours."
        ),
    ),
    "cart_abandoned": NotificationEventDef(
        key="cart_abandoned",
        label="Abandoned cart",
        group=EVENT_GROUP_MARKETING,
        description="Sent when a logged-in user's cart has been inactive past the configured delay.",
        channels=("email", "sms", "push"),
        placeholders=("cart_url", "store_name", "customer_name", "subtotal_cents"),
        default_subject="You left items in your cart",
        default_body=(
            "Hi {customer_name},\n\n"
            "You still have items waiting in your cart at {store_name}.\n\n"
            "Continue checkout: {cart_url}"
        ),
    ),
}

ORDER_STATUS_EVENT_MAP: dict[tuple[str, str], str] = {
    ("pending", "paid"): "order_confirmation",
    ("paid", "shipped"): "order_shipped",
    ("shipped", "delivered"): "order_delivered",
}


def get_event(event_key: str) -> NotificationEventDef | None:
    return NOTIFICATION_EVENTS.get(event_key)


def list_events() -> list[NotificationEventDef]:
    return list(NOTIFICATION_EVENTS.values())


def event_supports_channel(event_key: str, channel: NotificationChannel) -> bool:
    event = get_event(event_key)
    return event is not None and channel in event.channels
