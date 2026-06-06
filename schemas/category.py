"""Category schemas.

Categories form a tree – a parent category can have child sub-categories.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Create ──────────────────────────────────────────────────────────


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10000)
    parent_id: Optional[int] = Field(default=None, description="ID of parent category (null for root)")
    sort_order: int = Field(default=0, ge=0)


# ── Update ──────────────────────────────────────────────────────────


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    slug: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=10000)
    parent_id: Optional[int] = Field(default=None)
    sort_order: Optional[int] = Field(default=None, ge=0)


# ── Read ────────────────────────────────────────────────────────────


class CategoryRead(BaseModel):
    id: int
    name: str
    slug: str
    description: Optional[str]
    parent_id: Optional[int]
    sort_order: int
    created_at: datetime
    updated_at: datetime
    children: List["CategoryRead"] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class CategoryList(BaseModel):
    items: List[CategoryRead]
    total: int
