"""Durable onboarded scopes (I06): the subscriptions an administrator registered."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class OnboardedScopeRow(Base):
    __tablename__ = "onboarded_scopes"

    subscription_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    registered_by: Mapped[str] = mapped_column(Text)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
