"""Site-wide storefront branding and contact settings (singleton row)."""

from typing import Any, List, Optional

from sqlalchemy import Boolean, Column, Integer, JSON, String, Text
from sqlmodel import Field

from app.db.base import ModelBase

DEFAULT_PRIVACY_POLICY_TITLE = "Privacy Policy"

# Starter text for new shops — merchants should adapt this to their business and jurisdiction.
DEFAULT_PRIVACY_POLICY_BODY = """\
This Privacy Policy describes how we collect, use, and share information when you use our online store.

Who we are
We operate this store and are responsible for the personal data we process in connection with your orders and account.

Information we collect
- Contact and account details you provide (such as name, email address, and shipping address)
- Order and payment-related information needed to fulfill purchases (payment details are typically processed by our payment provider)
- Technical data such as IP address, browser type, and basic usage data needed to run and secure the store
- Communications you send us (for example support requests)

How we use your information
- To process and fulfill orders, including shipping and returns
- To create and manage your account, if you register
- To communicate about your orders, account, or support requests
- To operate, secure, and improve the store (including fraud prevention)
- To comply with legal obligations

Cookies and similar technologies
We use necessary cookies and similar technologies to run the store (for example session and security features). If we use optional analytics or marketing tools, we will describe them here and, where required, ask for your consent.

Sharing your information
We share personal data only as needed with service providers that help us run the store (such as hosting, payment, shipping, and email providers), or when required by law. We do not sell your personal data.

Data retention
We keep personal data only as long as needed for the purposes above, including order records and legal retention requirements, then delete or anonymize it where appropriate.

Your rights
Depending on where you live, you may have rights to access, correct, delete, or restrict use of your personal data, and to object to certain processing or request data portability. To exercise these rights, contact us using the details below.

Contact
If you have questions about this policy or your personal data, contact us at the support email shown on this store.

Updates
We may update this Privacy Policy from time to time. The effective date on this page shows when it last changed.

This text is a starting template only. Customize it for your business, products, tools, and local legal requirements before publishing.\
"""

DEFAULT_ABOUT_PAGE_TITLE = "About"

DEFAULT_ABOUT_PAGE_BODY = """\
Welcome to our store.

We are a small team dedicated to offering quality products and straightforward shopping. Tell your customers who you are, what you sell, and what makes your shop different.

This text is a starting template only. Customize it with your story before publishing.\
"""

DEFAULT_ABOUT_CONTACT_BODY = """\
Have a question about an order or our products? We are happy to help.

Add your business hours, shipping region, or other contact details here. If a support email is set in site settings, it will appear below as a contact link.\
"""


class SiteSettings(ModelBase, table=True):
    """Global site branding used by storefront, admin, and notifications."""

    __tablename__ = "site_settings"

    store_name: str = Field(
        default="Oshkelosh",
        sa_column=Column(String(255), nullable=False, server_default="Oshkelosh"),
    )
    logo_url: Optional[str] = Field(default=None, sa_column=Column(String(2048), nullable=True))
    favicon_url: Optional[str] = Field(default=None, sa_column=Column(String(2048), nullable=True))
    primary_color: str = Field(
        default="#2563eb",
        sa_column=Column(String(32), nullable=False, server_default="#2563eb"),
    )
    secondary_color: str = Field(
        default="#64748b",
        sa_column=Column(String(32), nullable=False, server_default="#64748b"),
    )
    font_family: str = Field(
        default="system-ui, sans-serif",
        sa_column=Column(String(255), nullable=False, server_default="system-ui, sans-serif"),
    )
    support_email: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))
    meta_description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    site_url: Optional[str] = Field(default=None, sa_column=Column(String(2048), nullable=True))
    shop_currency: str = Field(
        default="USD",
        sa_column=Column(String(3), nullable=False, server_default="USD"),
    )

    # Built-in tax rules (defaults: 8% tax enabled)
    tax_enabled: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="1"),
    )
    tax_inclusive: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="0"),
    )
    tax_rate_bps: int = Field(
        default=800,
        ge=0,
        sa_column=Column(Integer, nullable=False, server_default="800"),
    )
    tax_zones_json: List[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )

    # Built-in shipping rules (defaults: $5 flat shipping)
    shipping_mode: str = Field(
        default="flat",
        sa_column=Column(String(32), nullable=False, server_default="flat"),
    )
    shipping_flat_cents: int = Field(
        default=500,
        ge=0,
        sa_column=Column(Integer, nullable=False, server_default="500"),
    )
    shipping_free_threshold_cents: Optional[int] = Field(
        default=None,
        ge=0,
        sa_column=Column(Integer, nullable=True),
    )
    shipping_zones_json: List[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )

    # Native abandoned cart recovery
    abandoned_cart_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="0"),
    )
    abandoned_cart_delay_hours: int = Field(
        default=24,
        ge=1,
        sa_column=Column(Integer, nullable=False, server_default="24"),
    )
    abandoned_cart_max_reminders: int = Field(
        default=1,
        ge=1,
        sa_column=Column(Integer, nullable=False, server_default="1"),
    )

    # Simple GDPR / cookie notice (dismissible; no consent gating)
    gdpr_banner_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="0"),
    )
    gdpr_banner_text: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # Built-in privacy policy page at /privacy
    privacy_policy_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="0"),
    )
    privacy_policy_title: str = Field(
        default=DEFAULT_PRIVACY_POLICY_TITLE,
        sa_column=Column(
            String(255),
            nullable=False,
            server_default=DEFAULT_PRIVACY_POLICY_TITLE,
        ),
    )
    privacy_policy_body: Optional[str] = Field(
        default=DEFAULT_PRIVACY_POLICY_BODY,
        sa_column=Column(Text, nullable=True),
    )
    privacy_policy_effective_date: Optional[str] = Field(
        default=None,
        sa_column=Column(String(10), nullable=True),
    )

    # Built-in about page at /about (About + Contact Us sections)
    about_page_enabled: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="0"),
    )
    about_page_title: str = Field(
        default=DEFAULT_ABOUT_PAGE_TITLE,
        sa_column=Column(
            String(255),
            nullable=False,
            server_default=DEFAULT_ABOUT_PAGE_TITLE,
        ),
    )
    about_page_body: Optional[str] = Field(
        default=DEFAULT_ABOUT_PAGE_BODY,
        sa_column=Column(Text, nullable=True),
    )
    about_contact_body: Optional[str] = Field(
        default=DEFAULT_ABOUT_CONTACT_BODY,
        sa_column=Column(Text, nullable=True),
    )
