"""Payment webhook orchestration schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class PaymentWebhookOutcome(BaseModel):
    """Structured webhook parse result (addon → core orchestration)."""

    handled: bool = True
    event_id: str = ""
    event_type: str = ""
    mark_paid: bool = False
    order_id: Optional[int] = None
    payment_id: Optional[str] = None
    payment_charge_id: Optional[str] = None
    customer_id: Optional[str] = None
    error: Optional[str] = None
