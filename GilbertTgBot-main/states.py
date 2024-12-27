from aiogram.fsm.state import State, StatesGroup
#Смотрит статус оплаты бота.

class PaymentState(StatesGroup):
    check_payment_status = State()
    successful_payment = State()

