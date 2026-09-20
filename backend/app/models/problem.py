from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Problem(Base):
    __tablename__ = "problems"
    
    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    allowed_languages: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: ["python"],
        server_default='["python"]',
    )
    active_case_version: Mapped[str] = mapped_column(
        String(50), nullable=False, default="v1", server_default="v1"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    @staticmethod
    def validate_allowed_languages(languages: list[str]) -> list[str]:
        supported = {"python", "cpp"}
        if not languages or any(language not in supported for language in languages):
            raise ValueError("allowed_languages must contain only python or cpp")
        if len(languages) != len(set(languages)):
            raise ValueError("allowed_languages must not contain duplicates")
        return languages