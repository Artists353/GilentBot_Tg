from aiogram.fsm.state import State, StatesGroup


class PaymentState(StatesGroup):
    check_payment_status = State()
    successful_payment = State()

