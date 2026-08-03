"""Import ORM models so SQLAlchemy mappers configure before PG queries."""


def bootstrap_orm_models() -> None:
    from app.models import user_data_stores  # noqa: F401
    from app.models.knowledge import KnowledgeBase  # noqa: F401
    from app.models.seo import Project  # noqa: F401
    from app.models.user import User  # noqa: F401
