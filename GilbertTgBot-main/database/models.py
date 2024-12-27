from datetime import datetime  # Импорт модуля для работы с датой и временем.
from typing import Literal  # Импорт для определения фиксированных значений переменных (литералов).

from sqlalchemy import Integer, String, Text, func  # Импорт типов данных и функций для работы с SQLAlchemy.
from sqlalchemy.ext.asyncio import AsyncAttrs  # Импорт для использования асинхронных атрибутов в моделях.
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column  # Импорт инструментов ORM для определения моделей.

# Определяем тип данных для статуса заказа. Возможные значения: "confirmed", "canceled", "new".
Status = Literal["confirmed", "canceled", "new"]

# Определяем базовый класс для всех моделей, который будет включать общие атрибуты.
class Base(AsyncAttrs, DeclarativeBase):
    # Поле created_at будет автоматически задавать время создания записи при добавлении в базу данных.
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

# Описание модели данных для представления заказа.
class Order(Base):
    """
    Модель заказа, используемая для хранения информации о заказах в базе данных.

    Атрибуты:
        tg_id: Telegram ID пользователя, связанный с заказом.
        order_id: Уникальный идентификатор заказа.
        amount: Сумма заказа.
        comment: Комментарий к заказу (опциональный параметр).
        address: Адрес доставки заказа (опциональный параметр).
        payment_id: Идентификатор платежа (опциональный параметр).
        status: Текущий статус заказа ("new", "confirmed", "canceled").
    """
    __tablename__ = "order"  # Указываем имя таблицы, в которой будут храниться заказы.

    tg_id: Mapped[int]  # Telegram ID пользователя, связанный с заказом.
    order_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True, unique=True, default=100  # Уникальный идентификатор заказа с автоинкрементом.
    )
    amount: Mapped[int] = mapped_column(Integer)  # Сумма заказа, указывается в целых числах (например, в копейках).
    comment: Mapped[str] = mapped_column(
        Text(750), nullable=True  # Комментарий к заказу с ограничением в 750 символов, не обязательное поле.
    )
    address: Mapped[str] = mapped_column(
        String(500), nullable=True  # Адрес доставки заказа, ограниченный 500 символами, не обязательное поле.
    )
    payment_id: Mapped[int] = mapped_column(
        Integer, nullable=True  # Идентификатор платежа, не обязательное поле.
    )
    status: Mapped[Status]  # Статус заказа, который может принимать значения "new", "confirmed", или "canceled".
