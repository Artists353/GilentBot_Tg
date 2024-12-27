from datetime import datetime
from typing import Literal

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Status = Literal["confirmed", "canceled", "new"]


class Base(AsyncAttrs, DeclarativeBase):
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Order(Base):
    """
    Модель заказа

    Атрибуты:
        tg_id - телеграм айди пользователя
        order_id - номер заказа
        amount - сумма в заказе
        comment - комментарий к заказу (опционально)
        address - адрес доставки заказа
        payment_id - идентификатор платежа
        status - статус заказа

    """
    __tablename__ = "order"

    tg_id: Mapped[int]
    order_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, unique=True, default=100)
    amount: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text(750), nullable=True)
    address: Mapped[str] = mapped_column(String(500), nullable=True)
    payment_id: Mapped[int] = mapped_column(Integer, nullable=True)
    status: Mapped[Status]
