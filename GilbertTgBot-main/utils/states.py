from aiogram.fsm.state import State, StatesGroup


class PaymentState(StatesGroup):
    payment_success = State()
