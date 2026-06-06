"""Pagination helpers."""

from typing import Any, Generic, List, TypeVar

from sqlmodel import SQLModel, select
from sqlmodel.orm.session import Session

T = TypeVar("T", bound=SQLModel)


def paginate(
    session: Session,
    model: type[T],
    page: int = 1,
    page_size: int = 20,
    filters: dict | None = None,
    order_by: str | None = None,
) -> dict[str, Any]:
    """Apply pagination to a SQLModel model query.

    Returns a dict with 'items', 'page', 'page_size', 'total', 'pages'.
    """
    stmt = select(model)

    if filters:
        for key, value in filters.items():
            if value is not None:
                column = getattr(model, key, None)
                if column is not None:
                    stmt = stmt.where(column == value)

    total = session.exec(select(session.bind.dialect.integer() if hasattr(session.bind.dialect, 'integer') else __import__('sqlalchemy').func.count()).select_from(stmt.subquery())).one()
    # Simpler approach: count directly
    count_stmt = select(__import__('sqlalchemy').func.count()).select_from(stmt.subquery())
    total = session.exec(count_stmt).one()

    if order_by:
        col = getattr(model, order_by, None)
        if col is not None:
            stmt = stmt.order_by(col.desc())

    items = session.exec(
        stmt.offset((page - 1) * page_size).limit(page_size)
    ).all()

    pages = (total + page_size - 1) // page_size if page_size > 0 else 0

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": pages,
    }
