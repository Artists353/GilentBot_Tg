from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from utils import logger

from .config import async_session
from .models import Order


async def get_valid_order_id() -> int:
    """
    Находим последний OrderId для инициализации платежа

    Возвращение:
        last_order_id - последний order_id

    """
    async with async_session() as session:
        last_order_id = await session.scalar(
            select(Order.order_id).order_by(Order.order_id.desc()).limit(1)
        )
        return (last_order_id or 0) + 1


async def get_amount(order_id: int) -> int | None:
    """ Получаем сумму заказа по order_id """
    async with async_session() as session:
        try:
            stmt = select(Order.amount).where(Order.order_id == order_id)
            result = await session.execute(stmt)
            amount = result.scalar_one_or_none()

            if not amount:
                raise ValueError(f"Сумма заказа с таким №{order_id} OrderId не найдена!")

            logger.info(f"Нашли {amount} сумму заказа c {order_id} OrderId")
            return amount

        except OperationalError as error:
            logger.error(f"Не удалось выполнить запрос в базу данных | Error: {error}")
            return


async def update_payment_data(
    order_id: int,
    status: str,
    payment_id: int = None
):
    """
    Находим и обновляем статус созданного заказа

    Атрибуты:
        order_id - номер заказа
        status - статус, на который обновляем

    """
    async with async_session() as session:
        try:
            stmt = select(Order).where(Order.order_id == order_id)
            result = await session.execute(stmt)
            order = result.scalar_one_or_none()

            if not order:
                raise ValueError(f"Заказ с таким №{order_id} не найден!")

            order.status = status
            order.payment_id = payment_id

            await session.commit()

        except OperationalError as error:
            logger.error(f"Не удалось выполнить запрос в базу данных | Error: {error}")
            return

        else:
            logger.info(f"Успешно обновили статус на {status} в базе данных по номеру платежа №{payment_id}")


async def init_new_payment(
    tg_id: int,
    amount: int,
    order_id: int,
    address: str,
    comment: str,
    status: str = "new",
    payment_id: int = None,
):
    """
    Заполняем базу данных:
        tg_id - телеграм айди пользователя
        amount - сумма заказа
        order_id - номер заказа
        address - адрес доставки заказа
        comment - комментарий к заказу
        status - статус (new)

    """
    async with async_session() as session:
        try:
            new_order = Order(
                tg_id=tg_id,
                order_id=order_id,
                amount=amount,
                comment=comment,
                address=address,
                status=status,
                payment_id=payment_id,
            )
            session.add(new_order)
            await session.commit()

        except OperationalError as error:
            logger.error(f"Не удалось выполнить запрос в базу данных | Error: {error}")
            return


async def check_amount_and_payment_id(
    payment_id: int,
    amount: int
) -> bool | None:
    """
    Сверяем payment_id и amount с базой данных

    Атрибуты:
        payment_id - айди платежа
        amount - сумма заказа

    """
    async with async_session() as session:
        try:
            stmt = select(
                Order.payment_id, Order.amount
            ).where(
                Order.payment_id == payment_id
            ).where(
                Order.amount == amount
            )
            result = await session.execute(stmt)
            row = result.one_or_none()

            if row:
                payment_id_db, amount_db = row
                payment_id_db, amount_db = int(payment_id_db), int(amount_db)
            else:
                logger.error(
                    f"В базе данных не был найден заказ с PaymentId {payment_id} и Amount {amount}!"
                )
                return False

            if payment_id_db != payment_id or amount_db != amount:
                return False

            logger.info(f"Полученная сумма {amount} и PaymentId соответствуют тем, что находятся в базе данных")
            return True

        except OperationalError as error:
            logger.error(f"Не удалось выполнить запрос в базу данных | Error: {error}")
            return


async def get_user_tg_id(
    payment_id: int,
    amount: int
) -> int | None:
    """
    Находим телеграм айди пользователя по его PaymentId и Amount

    Атрибуты:
        payment_id - номер платежа
        amount - сумма заказа

    """
    async with async_session() as session:
        try:
            stmt = select(
                Order.tg_id
            ).where(
                Order.payment_id == payment_id
            ).where(
                Order.amount == amount
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row:
                logger.info(f"Нашли telegram_id пользователя: {row}")
                return row

            return

        except OperationalError as error:
            logger.error(f"Не удалось выполнить запрос в базу данных | Error: {error}")
            return
