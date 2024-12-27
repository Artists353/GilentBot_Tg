from sqlalchemy import select, update  # Импорт функций для создания SQL-запросов (выборка и обновление).
from sqlalchemy.exc import OperationalError  # Импорт исключения для обработки ошибок базы данных.

from utils import logger  # Импорт логгера для записи информации и ошибок.

from .config import async_session  # Импорт асинхронной сессии для работы с базой данных.
from .models import Order  # Импорт модели "Order" для работы с таблицей заказов.


async def get_valid_order_id() -> int:
    """
    Находим последний OrderId для инициализации платежа

    Возвращение:
        last_order_id - последний order_id

    """
    async with async_session() as session:  # Создаем асинхронную сессию.
        last_order_id = await session.scalar(  # Выполняем запрос на получение последнего order_id.
            select(Order.order_id).order_by(Order.order_id.desc()).limit(1)  # Сортируем по убыванию и берем первую запись.
        )
        return (last_order_id or 0) + 1  # Если записи нет, возвращаем 1, иначе увеличиваем на 1.


async def get_amount(order_id: int) -> int | None:
    """ Получаем сумму заказа по order_id """
    async with async_session() as session:  # Создаем асинхронную сессию.
        try:
            stmt = select(Order.amount).where(Order.order_id == order_id)  # Формируем запрос на выбор суммы заказа.
            result = await session.execute(stmt)  # Выполняем запрос.
            amount = result.scalar_one_or_none()  # Получаем единственное значение или None.

            if not amount:  # Если сумма не найдена, выбрасываем исключение.
                raise ValueError(f"Сумма заказа с таким №{order_id} OrderId не найдена!")

            logger.info(f"Нашли {amount} сумму заказа c {order_id} OrderId")  # Логируем найденную сумму.
            return amount  # Возвращаем сумму.

        except OperationalError as error:  # Обрабатываем ошибки базы данных.
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
    async with async_session() as session:  # Создаем асинхронную сессию.
        try:
            stmt = select(Order).where(Order.order_id == order_id)  # Формируем запрос на выбор заказа по order_id.
            result = await session.execute(stmt)  # Выполняем запрос.
            order = result.scalar_one_or_none()  # Получаем объект заказа или None.

            if not order:  # Если заказ не найден, выбрасываем исключение.
                raise ValueError(f"Заказ с таким №{order_id} не найден!")

            order.status = status  # Обновляем статус заказа.
            order.payment_id = payment_id  # Устанавливаем идентификатор платежа, если указан.

            await session.commit()  # Фиксируем изменения в базе данных.

        except OperationalError as error:  # Обрабатываем ошибки базы данных.
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
    async with async_session() as session:  # Создаем асинхронную сессию.
        try:
            new_order = Order(  # Создаем новый объект заказа.
                tg_id=tg_id,
                order_id=order_id,
                amount=amount,
                comment=comment,
                address=address,
                status=status,
                payment_id=payment_id,
            )
            session.add(new_order)  # Добавляем новый заказ в сессию.
            await session.commit()  # Сохраняем изменения в базе данных.

        except OperationalError as error:  # Обрабатываем ошибки базы данных.
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
    async with async_session() as session:  # Создаем асинхронную сессию.
        try:
            stmt = select(  # Формируем запрос на выбор платежа и суммы.
                Order.payment_id, Order.amount
            ).where(
                Order.payment_id == payment_id
            ).where(
                Order.amount == amount
            )
            result = await session.execute(stmt)  # Выполняем запрос.
            row = result.one_or_none()  # Получаем единственную запись или None.

            if row:  # Если запись найдена, извлекаем данные.
                payment_id_db, amount_db = row
                payment_id_db, amount_db = int(payment_id_db), int(amount_db)
            else:  # Если записи нет, логируем ошибку и возвращаем False.
                logger.error(
                    f"В базе данных не был найден заказ с PaymentId {payment_id} и Amount {amount}!"
                )
                return False

            if payment_id_db != payment_id or amount_db != amount:  # Сравниваем данные.
                return False

            logger.info(f"Полученная сумма {amount} и PaymentId соответствуют тем, что находятся в базе данных")
            return True  # Возвращаем True, если данные совпадают.

        except OperationalError as error:  # Обрабатываем ошибки базы данных.
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
    async with async_session() as session:  # Создаем асинхронную сессию.
        try:
            stmt = select(  # Формируем запрос на выбор телеграм ID.
                Order.tg_id
            ).where(
                Order.payment_id == payment_id
            ).where(
                Order.amount == amount
            )
            result = await session.execute(stmt)  # Выполняем запрос.
            row = result.scalar_one_or_none()  # Получаем единственное значение или None.

            if row:  # Если найдено, логируем ID пользователя и возвращаем его.
                logger.info(f"Нашли telegram_id пользователя: {row}")
                return row

            return  # Если ничего не найдено, возвращаем None.

        except OperationalError as error:  # Обрабатываем ошибки базы данных.
            logger.error(f"Не удалось выполнить запрос в базу данных | Error: {error}")
            return
