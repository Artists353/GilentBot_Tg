import asyncio  # Асинхронные операции.
import hashlib  # Хэширование данных, например для генерации токенов.
import json  # Работа с JSON данными.
import logging  # Логирование событий и ошибок.
import random  # Генерация случайных чисел, например для сообщений об ошибках.
import uuid  # Генерация уникальных идентификаторов.
from datetime import datetime, timedelta  # Работа с датами и временем.
from typing import Any, Dict  # Типизация в Python.

import httpx  # Асинхронные HTTP-запросы.
from aiogram import Bot, Dispatcher, F, Router, types  # Основные классы и функции библиотеки aiogram для создания Telegram-ботов.
from aiogram.client.default import DefaultBotProperties  # Настройки бота по умолчанию.
from aiogram.enums import ParseMode  # Определяет режим парсинга (например, HTML).
from aiogram.filters import Command, CommandStart  # Фильтры для обработки команд бота.
from aiogram.fsm.context import FSMContext  # Контекст для управления состояниями FSM (Finite State Machine).
from aiogram.types import (FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup)  # Типы Telegram-объектов.
from aiogram.webhook.aiohttp_server import (SimpleRequestHandler, setup_application)  # Работа с вебхуками.
from aiohttp import web  # Работа с веб-сервером.
from aiohttp.web_request import Request  # Класс для обработки веб-запросов.

import config as cf  # Импорт пользовательских настроек (например, токен бота).
from database import Base, engine  # Импорт базы данных и механизма ORM.
from database.queries import (check_amount_and_payment_id, get_amount, get_user_tg_id, init_new_payment, update_payment_data)  # Запросы к базе данных.
from utils import PaymentState, logger  # Пользовательские утилиты, включая логирование.

# Настройки бота по умолчанию, например парсинг HTML.
default_properties: DefaultBotProperties = DefaultBotProperties(parse_mode=ParseMode.HTML)

# Инициализация бота и диспетчера.
bot: Bot = Bot(token=cf.BOT_TOKEN, default=default_properties)
dp: Dispatcher = Dispatcher()

# Базовый URL приложения, например, от ngrok.
APP_BASE_URL: str = ""

# Настройки для работы с Tinkoff API.
terminal_key = ""  # Токен терминала.
secret = ""  # Секретный ключ.

# Кастомное исключение для ошибок работы с Tinkoff API.
class TinkoffAPIException(Exception):
    pass

# Клиент для взаимодействия с Tinkoff API.
class TinkoffAcquiringAPIClient:
    API_ENDPOINT = "https://securepay.tinkoff.ru/v2/"  # Базовый URL API Tinkoff.

    def __init__(self, terminal_key: str, secret: str):
        self.terminal_key = terminal_key  # Сохраняем ключ терминала.
        self.secret = secret  # Сохраняем секретный ключ.
        self.logger = logging.getLogger(__name__)  # Логгер для класса.
        logging.basicConfig(level=logging.INFO)  # Устанавливаем уровень логирования.

    async def send_request(self, endpoint, payload) -> Dict | None:
        """ Отправка запроса к API """
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient() as client:
            payload['TerminalKey'] = self.terminal_key  # Добавляем TerminalKey в запрос.
            payload['Token'] = self.generate_token(payload)  # Генерируем токен для защиты данных.
            self.logger.info(f"Отправляемые данные на сервере в методе {endpoint}: {payload = }")

            try:
                response = await client.post(
                    url=self.API_ENDPOINT + endpoint,  # URL запроса.
                    json=payload,  # Тело запроса в формате JSON.
                    headers=headers,  # Заголовки запроса.
                )
            except httpx.ConnectError as error:  # Ошибка соединения.
                self.logger.error(
                    f"Произошла ошибка при подключении | Error: {error}"
                )
                return
            except httpx.ConnectTimeout as error:  # Ошибка таймаута.
                self.logger.error(
                    f"Прошел таймаут | Error: {error}"
                )
                return

            self.logger.info(f"Полученный ответ: {response = }")
            try:
                response_data: Dict = response.json()  # Преобразуем ответ в JSON.
            except json.JSONDecodeError as error:  # Ошибка парсинга JSON.
                logging.error(
                    f"Произошла ошибка {error.__class__.__name__} при десериализации ответа JSON"
                )
                return

            self.logger.info(f"Полученный ответ: {response_data}")
            if response.status_code != 200 or not response_data.get('Success'):
                error_message = response_data.get('Message', 'Unknown error')
                self.logger.error(f'API request failed: {error_message}')
                raise TinkoffAPIException(error_message)

            return response_data

    def generate_token(self, params):
        """ Генерируем токен для отправки в запросе """
        ignore_keys = ['Shops', 'Receipt', 'DATA']  # Игнорируем некоторые ключи в запросе.
        _params = params.copy()
        for key in ignore_keys:
            if key in _params:
                del _params[key]

        params['Password'] = self.secret  # Добавляем пароль в параметры.
        _params["Password"] = self.secret
        sorted_params = dict(sorted(_params.items(), key=lambda x: x[0]))  # Сортируем параметры.
        token_str = ''.join(str(value) for _, value in sorted_params.items())  # Объединяем значения в строку.
        return hashlib.sha256(token_str.encode('utf-8')).hexdigest()  # Генерируем SHA256 хэш.

    # Остальной код, в том числе обработчики, аннотации к которым добавлю при необходимости.

    async def init_payment(self,
                           amount: int,
                           order_id: str,
                           description: str,
                           data: dict = None,
                           receipt=None,
                           success_url: str = None,
                           fail_url: str = None,
                           notification_url: str = None
                           ):
        # Tinkoff API expects amount in kopecks, hence multiplying by 100
        params = {
            'Amount': amount,
            'OrderId': order_id,
            'Description': description,
        }
        # Добавляем SuccessURL
        if success_url:
            params['SuccessURL'] = success_url
        # Добавляем FailURL
        if fail_url:
            params['FailURL'] = fail_url
        # Добавляем Receipt
        if receipt:
            params['Receipt'] = receipt
        # Добавляем NotificationURL
        if notification_url:
            params["NotificationURL"] = notification_url
        # Добавляем DATA
        if data:
            params["DATA"] = data

        return await self.send_request('Init', params)

    async def get_payment_state(self, payment_id: int) -> Dict:
        params = {'PaymentId': payment_id}
        return await self.send_request('GetState', params)

    async def confirm_payment(self, payment_id: int):
        params = {'PaymentId': payment_id}
        return await self.send_request('Confirm', params)

    async def cancel_payment(self, payment_id: int):
        params = {'PaymentId': payment_id}
        return await self.send_request('Cancel', params)

#===================================================================================================================================
@dp.message(CommandStart())
async def start(message: types.Message, state: FSMContext):
    print(message.from_user.username, 'Start')
    await state.update_data(general_message = None, promo_message = None, lecture_messages = None, conf = None,
                            basket_list= None, basket_message = None, basket_messages= None, basket_sum= None, num_conf = None)
    if cf.conf:
        photo = open('Image/conf.jpeg', 'rb')
        await bot.send_photo(message.chat.id, photo, caption= cf.conf_descript,
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                InlineKeyboardButton(text="Зарегистрироваться на конференцию", callback_data= 'reg'),
                                InlineKeyboardButton(text="Перейти к видеоматериалам", callback_data= 'general')                                 
                                ])
                            )
    else:
        await display_conferences(message, state)

#===================================================================================================================================
@dp.callback_query(lambda c: c.data.startswith('reg'))
async def registration(callback_query: types.CallbackQuery):
    text = "Скоро, здесь Вы сможете регистрироваться на наши конференции, а пока мы работаем над этим функционалом."   
    await callback_query.answer(text)    

#===================================================================================================================================
@dp.callback_query(lambda c: c.data.startswith('general'))
async def display_conferences(callback_query: types.CallbackQuery, state: FSMContext):
    print(callback_query.from_user.username, 'General')
    state_data = await state.get_data()
    general_message = state_data.get("general_message")
    basket_message = state_data.get("basket_message")
    lecture_messages = state_data.get("lecture_messages")
    basket_messages = state_data.get("basket_messages")
    promo_message = state_data.get("promo_message")
    invoice = state_data.get("invoice")
    # Формируем параметры главного сообщения, текст и кнопки конференций
    buttons = [[InlineKeyboardButton(text=cf.confs[conf]["title"], callback_data=f"conf_{conf}")]
               for conf in cf.confs]
    caption_text = (f'⬇️ Здесь живут записи прошедших встреч <b>Gilbert Club</b>\n'
                    '\nВы можете купить отдельные лекции или все мероприятия целиком, нажав соответствующие кнопки\n'
                    '\nДля покупки мерча нажмите кнопку: ❗️МЕРЧ❗️\n🤓')
    # Проверка наличия сообщений промо, лекции, корзина, invoice
    if promo_message:
        await promo_message.delete()
    if lecture_messages:
        print(callback_query.from_user.username, 'delete lectures')
        lecture_messages = await delete_messages(general_message.chat.id, lecture_messages)
    if basket_messages:
        print(callback_query.from_user.username, 'delete basket messages')
        basket_messages = await delete_messages(general_message.chat.id, basket_messages)
        if basket_message:
            await basket_message.edit_reply_markup(reply_markup= InlineKeyboardMarkup(inline_keyboard=[
                                            [InlineKeyboardButton(text='Открыть корзину', callback_data= "basket_open")]]))
    if invoice:
        await invoice.delete()
        await basket_message.edit_reply_markup(reply_markup= InlineKeyboardMarkup(inline_keyboard=[
                                            [InlineKeyboardButton(text='Открыть корзину', callback_data= "basket_open")]]))
    # Проверка главного сообщения (изменить или создать новое)
    if general_message:
        await general_message.edit_caption(caption=caption_text, reply_markup= InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback_query.answer()
    else:
        photo = FSInputFile('Image/Video.jpg')
        general_message = await bot.send_photo(callback_query.from_user.id, photo= photo, caption= caption_text, 
                                               reply_markup= InlineKeyboardMarkup(inline_keyboard=buttons))
    # Сохранем параметры в state
    await state.update_data(general_message= general_message, lecture_messages= lecture_messages, 
                            basket_messages= basket_messages, promo_message = None, num_conf = None, invoice = None)

#===================================================================================================================================
@dp.callback_query(lambda c: c.data.startswith('conf_'))
async def select_conference(callback_query: types.CallbackQuery, state: FSMContext):
    print(callback_query.from_user.username, 'Select conferences')
    state_data = await state.get_data()
    general_message = state_data.get("general_message")
    basket_list = state_data.get("basket_list")

    if not general_message:
        general_message = callback_query.message

    data = callback_query.data.split('_')
    num_conf = data[1]
    conf = cf.confs[num_conf]
    lects = conf["lectures"]

    text = f'<b>{conf["title"]}:</b>\n'
    for num_lect in lects:
        lect = lects[num_lect]
        text += f'\n{conf["lable"]} {lect[1]}\n<i>{lect[0]}</i>\n'

    count_b_lect = 0
    if basket_list:
        for b_conf in basket_list:
            if b_conf == num_conf:
                count_b_lect = len(basket_list[num_conf])

    button_1 = InlineKeyboardButton(text='Назад ⤴️', callback_data="general")
    if count_b_lect == len(lects):
        text += f'\n\n👍 <b>Все лекции данной конференции у вас в корзине</b> 👇'
        buttons = [[button_1]]
    else:
        if num_conf == '0':
            buttons = [[InlineKeyboardButton(text='Посмотреть мерч', callback_data=f"open_lectures")],
                       [button_1]]
        else:
            text += f'\n👍 <b>Стоимость всех лекций конференции со скидкой {conf["price"]}₽</b>'
            buttons = [[InlineKeyboardButton(text=f'Купить все лекции со скидкой', callback_data=f"lect_all")],
                       [InlineKeyboardButton(text='Купить лекции по отдельности', callback_data=f"open_lectures")],
                       [InlineKeyboardButton(text='Использовать промокод', callback_data=f"promocode")],
                       [button_1]]
    await general_message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.update_data(num_conf=num_conf, general_message=general_message)
    await callback_query.answer()

#===================================================================================================================================
@dp.callback_query(lambda c: c.data.startswith('open_lectures'))
async def display_lectures(callback_query: types.CallbackQuery, state: FSMContext):
    print(callback_query.from_user.username, 'Display lectures')
    state_data = await state.get_data()
    general_message = state_data.get("general_message")
    basket_list = state_data.get("basket_list")
    num_conf = state_data.get("num_conf")
    conf = cf.confs[num_conf]
    lects = conf["lectures"]

    caption_text = f'<b>{conf["title"]}</b>'
    buttons = [[InlineKeyboardButton(text='Назад ⤴️', callback_data= "general")]]
    if num_conf != '0':
        caption_text += f'\n\n👍 <b>Выгодно купить все лекции со скидкой, за {conf["price"]}₽, жми 👇</b>'
        buttons.insert(0, [InlineKeyboardButton(text=f'Купить все лекции со скидкой', callback_data= f"lect_all")])        
    await general_message.edit_caption(caption=caption_text, reply_markup= InlineKeyboardMarkup(inline_keyboard=buttons))

    b_lects = dict()
    if basket_list:
        if num_conf in basket_list:
            b_lects = basket_list[num_conf]

    await callback_query.answer('Дождитесь загрузки информации')
    lecture_messages = []
    for num_lect in lects:
        if num_lect not in b_lects:
            lect = lects[num_lect]
            photo = FSInputFile(f'Image/{num_conf}/{num_lect}.png')
            caption_text = f'\n<b>{lect[1]}</b>\n{lect[2]}\n<i>{lect[0]}</i>\n'
            message = await bot.send_photo(general_message.chat.id, photo= photo, caption= caption_text,
                                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                               [InlineKeyboardButton(text=f'Купить за {lect[3]}₽', callback_data= f"lect_{num_lect}")],
                                               [InlineKeyboardButton(text='Назад ⤴️', callback_data= "general")]]))
            lecture_messages.append(message.message_id)
            await asyncio.sleep(0.5)
    #await message.edit_reply_markup(reply_markup= InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Назад ⤴️', callback_data= "general")]]))
    await state.update_data(lecture_messages= lecture_messages)

#===================================================================================================================================
@dp.callback_query(lambda c: c.data.startswith('lect_'))
async def selected_lectures(callback_query: types.CallbackQuery, state: FSMContext):
    print(callback_query.from_user.username, 'selected_lectures')
    state_data = await state.get_data()
    lecture_messages = state_data.get("lecture_messages")
    basket_list = state_data.get("basket_list")

    num_conf = state_data.get("num_conf")
    num_lect = callback_query.data.split('_')[1]

    if not basket_list:
        basket_list = dict()
    if not lecture_messages:
        lecture_messages = []

    if num_lect == 'all':
        if num_conf in basket_list:
            del basket_list[num_conf]
        basket_list[num_conf] = cf.confs[num_conf]['lectures'].copy()
    else:
        lect = cf.confs[num_conf]['lectures'][num_lect]
        if num_conf in basket_list:
            basket_list[num_conf][num_lect] = lect
        else:
            basket_list[num_conf] = {num_lect: lect}
        await callback_query.message.delete()
        lecture_messages.remove(callback_query.message.message_id)

    await state.update_data(basket_list=basket_list, lecture_messages=lecture_messages)
    await create_basket_message(callback_query.message.chat.id, state, [['Открыть корзину', 'basket_open']])
    if len(lecture_messages) == 0 or num_lect == 'all':
        await display_conferences(callback_query, state)

#===================================================================================================================================
async def create_basket_message(chat_id, state, buttons_list):
    print('create_basket')
    state_data = await state.get_data()
    basket_message = state_data.get("basket_message")

    order = await summation(state)
    buttons = []
    for button in buttons_list:
        buttons.append([InlineKeyboardButton(text= button[0], callback_data= button[1])])
    keyboard = InlineKeyboardMarkup(inline_keyboard= buttons)
    text = f'<b>В корзине:</b>\n{order[1]} поз. на сумму <b>{order[0]}₽</b>'
    if basket_message:
        await basket_message.edit_caption(caption=text, reply_markup= keyboard)
    else:
        photo = FSInputFile('Image/Basket.jpg')
        basket_message = await bot.send_photo(chat_id, photo, caption= text, reply_markup= keyboard)
        await state.update_data(basket_message= basket_message)

#===================================================================================================================================
async def delete_messages(chat_id, list_messages):
    if len(list_messages) > 0:
        for message in list_messages:
            try:
                await bot.delete_message(chat_id, message)
            except:
                continue
        return None

#===================================================================================================================================
async def summation(state):
    state_data = await state.get_data()
    basket_list = state_data.get("basket_list")
    shipping_address = False
    sum_order = 0
    count_order = 0
    for num_conf in basket_list:
        if num_conf == '0':
            shipping_address = True
        conf = cf.confs[num_conf]['lectures']
        b_conf = basket_list[num_conf]
        count_order += len(b_conf)
        if len(b_conf) == len(conf):
            sum_order += int(cf.confs[num_conf]['price'])
        else:
            for num_lect in b_conf:
                lect = b_conf[num_lect]
                sum_order += int(lect[3])
    await state.update_data(basket_sum= sum_order, shipping_address = shipping_address)
    return [sum_order, count_order]

#===================================================================================================================================
@dp.callback_query(lambda c: c.data.startswith('basket_'))
async def basket(callback_query: types.CallbackQuery, state: FSMContext):
    print(callback_query.from_user.username, 'basket')
    state_data = await state.get_data()
    general_message = state_data.get("general_message")
    lecture_messages = state_data.get("lecture_messages")
    basket_list = state_data.get("basket_list")
    basket_message = state_data.get("basket_message")
    data = callback_query.data.split('_')
    select = data[1]

    if select == 'open':
        if lecture_messages:
            lecture_messages = await delete_messages(callback_query.message.chat.id, lecture_messages)
        await general_message.edit_caption(caption= '', reply_markup= InlineKeyboardMarkup(inline_keyboard= [
                                                    [InlineKeyboardButton(text= 'Назад ⤴️', callback_data= "general")]]))
        await basket_message.edit_reply_markup(reply_markup= InlineKeyboardMarkup(inline_keyboard= [
                                                    [InlineKeyboardButton(text= 'Оплатить 💵', callback_data= "pay")],
                                                    [InlineKeyboardButton(text= 'Очистить корзину', callback_data= "basket_clear")]]))
        basket_messages = []
        for num_conf in basket_list:
            b_lect = basket_list[num_conf]
            for num_lect in b_lect:
                lect = b_lect[num_lect]
                text = f'<b>{lect[1]}</b>\n<i>{lect[0]}</i>'
                button = InlineKeyboardButton(text= 'Удалить ❌', callback_data= f"basket_{num_conf}_{num_lect}")    
                keyboard = InlineKeyboardMarkup(inline_keyboard= [[button]])
                message = await general_message.answer(text= text, reply_markup= keyboard)
                basket_messages.append(message.message_id)
                await asyncio.sleep(0.5)
        await state.update_data(basket_messages= basket_messages, lecture_messages= lecture_messages)
    elif select == 'clear':
        await basket_message.delete()
        await state.update_data(basket_message= None, basket_list= None, basket_sum= 0)
        await display_conferences(callback_query, state)
    else:
        num_conf = select
        num_lect = data[2]
        if len(basket_list[num_conf]) > 1:
            del basket_list[num_conf][num_lect]
        else:
            del basket_list[num_conf]
        await callback_query.message.delete()
        await state.update_data(basket_list= basket_list)
        if len(basket_list) == 0:
            await basket_message.delete()
            await state.update_data(basket_message= None, basket_sum= 0)
            await display_conferences(callback_query, state)
        else:
            await create_basket_message(basket_message.chat.id, state,
                                        [['Оплатить 💵', 'pay'], ['Очистить корзину', 'basket_clear']])

#===================================================================================================================================
@dp.callback_query(lambda c: c.data.startswith('promocode'))
async def select_promocode(callback_query: types.CallbackQuery, state: FSMContext):
    print(callback_query.from_user.username, 'select_promocode')
    state_data = await state.get_data()
    general_message = state_data.get("general_message")
    basket_message = state_data.get("basket_message")

    if basket_message:
        await basket_message.delete()
    if general_message:
        await general_message.edit_reply_markup(reply_markup= InlineKeyboardMarkup(inline_keyboard=[]))

    photo = FSInputFile('Image/Promo.jpg')
    text = '<b>Отправьте сообщение с промокодом</b>'
    promo_message = await bot.send_photo(callback_query.from_user.id, photo, caption= text,
                                         reply_markup= InlineKeyboardMarkup(inline_keyboard= [
                                             [InlineKeyboardButton(text= 'Назад ⤴️', callback_data= "general")]]))    
    await state.update_data(basket_message = None, promo_message= promo_message, basket_list= None)

#===================================================================================================================================
@dp.message(F.content_type)
async def promocode(message: types.Message, state: FSMContext):
    print('promocode')
    state_data = await state.get_data()
    promo_message = state_data.get("promo_message")
    basket_list = state_data.get("basket_list")
    num_conf = state_data.get("num_conf")
    '''
    if message.from_user.id in cf.admins:
        if message.content_type == 'video':
            print(message.caption, message.video.file_id)
            await message.answer('Файл получен и зарегистрирован.')
        return
    '''
    if promo_message and message.text:
        buttons = []
        # проверка промокода
        with open('promocodes.json', 'r') as f:
            promocodes = json.load(f)
        if message.text in promocodes[num_conf]:
            promocodes[num_conf].remove(message.text)
            with open('promocodes.json', 'w') as f:
                json.dump(promocodes, f)
            basket_list = {num_conf: cf.confs[num_conf]['lectures']}
            text = '<b>👍 Отлично!\nВаш промокод принят.\nОжидайте загрузки материалов.</b>'
        else:
            buttons.append([InlineKeyboardButton(text= 'Назад ⤴️', callback_data= "general")])
            texts = ['Извините, но этот промокод недействителен. Пожалуйста, проверьте и отправьте еще разок.',
                    'К сожалению, вы ввели неверный промокод. Пожалуйста, проверьте его и попробуйте снова.',
                    'Промокод, который вы ввели, недействителен. Давайте попробуем еще раз.',
                    'Упс, похоже, с промокодом что-то не так. Введите его заново.',
                    'Извините, но этот промокод не сработал. Проверить ваш промокод и отправьте его снова.']
            while(True):
                text = random.choice(texts)
                if promo_message.caption != text:
                    break
        promo_message = await promo_message.edit_caption(caption= f'<b>{text}</b>',
                                                         reply_markup= InlineKeyboardMarkup(inline_keyboard= buttons))
        await state.update_data(promo_message= promo_message, basket_list= basket_list)
        if basket_list:
            await issuing_order(message.chat.id, state)
    await message.delete()

#===================================================================================================================================
@dp.callback_query(lambda c: c.data.startswith('pay'))
async def pay(callback_query: types.CallbackQuery, state: FSMContext):
    print(callback_query.from_user.username, 'pay')
    # await callback_query.answer('Сервис оплаты временно не работает.\nПриносим свои извинения.', show_alert=True)
    chat_id = callback_query.message.chat.id
    state_data = await state.get_data()
    comment = state_data.get("basket_messages")
    address = state_data.get("shipping_address")
    basket_sum = state_data.get("basket_sum")
    amount = int(basket_sum * 100)

    if comment:
        await delete_messages(chat_id, comment)

    comment = "Комментарий к заказу"
    # Данные, которые я использовал для тестирования !!!
    user_tg_id: int = callback_query.from_user.id
    OrderId: int = int(str(uuid.uuid4().int)[: 10])

    # Создали клиент
    client = TinkoffAcquiringAPIClient(terminal_key=terminal_key, secret=secret)
    # Инициализируем платежную сессию
    try:
        response = await client.init_payment(
            amount=amount,
            order_id=str(OrderId),
            description='Видеозаписи лекций и/или мерч',
            notification_url=f"{APP_BASE_URL}/payment_hook",
            success_url=f"{APP_BASE_URL}/payment/success",
            fail_url=f"{APP_BASE_URL}/payment/fail",
        )
    except Exception as error:
        logger.error(f"Произошла ошибка при инициализации платежной сессии | Error: {error}")
        return

    if response.get("PaymentURL"):
        payment_url = response.get("PaymentURL")
        payment_id = response.get("PaymentId")
        # Заносим в базу данных инициализированный платеж
        await init_new_payment(
            tg_id=user_tg_id,
            amount=amount,
            order_id=OrderId,
            address=address,
            comment=comment,
            payment_id=payment_id,
        )
        logger.info(f"Создали новый заказ c OrderId {OrderId}! Отправляем ссылку на оплату")
        await callback_query.bot.send_message(chat_id, text=f"Для оплаты перейдите по ссылке:\n{payment_url}")

    else:
        await callback_query.answer(f"Произошла ошибка при создании платежа.\nПриносим свои извинения")


async def process_payment(request: Request, state: FSMContext):
    """
    Хэндлер для отлова вебхука и обработки статуса платежа

    """
    data: Dict = await request.json()
    logger.info(f"Отловили вебхук в process_payment и получили данные.")

    amount: int = int(data.get("Amount"))
    order_id: int = int(data.get("OrderId"))
    payment_id: int = int(data.get("PaymentId"))

    user_id = await get_user_tg_id(
        payment_id=payment_id,
        amount=amount,
    )

    # Если оплата прошла успешно
    if data.get("Status") == "CONFIRMED" and data.get("Success") is True:
        curr_amount: int = await get_amount(order_id)

        # сравниваем сумму заказа с тем, что у нас в базе
        if curr_amount == amount:
            logger.info(f"Платеж №{payment_id} на сумму {amount / 100} руб прошел успешно! Обновляем статус в базе данных")

            try:
                client = TinkoffAcquiringAPIClient(terminal_key=terminal_key, secret=secret)
                response = await client.get_payment_state(
                    payment_id=payment_id
                )
                payment_id_get_state = response.get("PaymentId")
                amount_get_state = response.get("Amount")
                result: bool = await check_amount_and_payment_id(
                    payment_id=payment_id_get_state,
                    amount=amount_get_state,
                )
                if not result:
                    logger.error(
                        f"Не удалось сравнить PaymentId и Amount с ранее созданными"
                    )

            except Exception as error:
                logger.error(
                    f"Не удалось отправить запрос на эндпоинт GetState на проверку статуса платежа {payment_id} | Error: {error}"
                )
                pass
            # Обновляем статус платежа на "confirmed"
            await update_payment_data(
                order_id=order_id,
                status="confirmed",
                payment_id=payment_id,
            )
            await bot.send_message(user_id, "Поздравляем 🥳 Вы успешно оплатили заказ!",
                                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                        InlineKeyboardButton(text="Получить", callback_data="get_order")
                                   ]]))

            return web.Response(text="OK", status=200)

    elif data.get("Status") == "REJECTED":
        logger.info(f"Неуспешный платеж на сумму {amount / 100} руб. Обновляем статус в базе данных")
        await update_payment_data(
            order_id=order_id,
            status="canceled",
            payment_id=payment_id,
        )
        await bot.send_message(user_id, text=(
            f"😔 К сожалению не удалось выполнить оплату\nПриходите к нам в следующий раз"
        ))

    return web.Response(text="OK", status=200)


@dp.callback_query(lambda c: c.data == "get_order")
async def get_order(callback_query: types.CallbackQuery, state: FSMContext):
    """
    Callback, который сработает при нажатии на кнопку c data get_order при успешной оплате

    """
    logger.info("Сработал callback_query хэндлер при нажатии на кнопку get_order")
    return
    # await process_pay(callback_query=callback_query, state=state)


@dp.message(PaymentState.payment_success) # F.content_type == "successful_payment"
async def process_pay(callback_query: types.CallbackQuery, state: FSMContext):
    logger.info(f"сработал process_pay ")
    state_data = await state.get_data()
    basket_message = state_data.get("basket_message")
    shipping_address = state_data.get("shipping_address")
    chat_id = callback_query.from_user.id

    # Оплата прошла
    text ='<b>👍 Оплата прошла успешно.\n📌 Видеофайлы загрузятся в течении 2 минут.</b>'
    if shipping_address:
        text += '\n📌 <b>Мерч отправим в течении 3 дней.</b>'
    await basket_message.edit_caption(caption= text)
    await issuing_order(chat_id, state)

#===================================================================================================================================
async def issuing_order(id_chat, state: FSMContext):
    print('issuing_order')
    state_data = await state.get_data()
    general_message = state_data.get("general_message")
    promo_message = state_data.get("promo_message")
    basket_message = state_data.get("basket_message")
    basket_list = state_data.get("basket_list")

    print(f"{general_message = }")
    print(f"{promo_message = }")
    print(f"{basket_message = }")
    print(f"{basket_list = }")

    await asyncio.sleep(3)
    merch = False
    for num_conf in basket_list:
        if num_conf == '0':
            merch = True
        else:
            b_conf = basket_list[num_conf]
            for num_lect in b_conf:
                lect = b_conf[num_lect]
                await bot.send_video(id_chat, video= lect[4], caption= f'<b>{lect[1]}</b>\n<i>{lect[0]}</i>', protect_content= True)
                await asyncio.sleep(1)    

    for message in [general_message, basket_message, promo_message]:
        if message:
            await message.delete()
    await state.update_data(basket_list= None, basket_messages= None, general_message = None, 
                            promo_message = None, basket_sum= None, invoice = None)

    photo = FSInputFile('Image/Lectors.jpg')
    text = f'<b>🤝 Благодарим вас за участие в нашем клубе</b>'
    if merch == True:
        text += f'\nМерч будет отправлен вам по указанному адресу, в течении 3 дней.'
    await bot.send_photo(id_chat, photo, caption= text,
                         reply_markup= InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text= 'Продолжить ▶️', callback_data= "restart")]]))

#===================================================================================================================================
@dp.callback_query(lambda c: c.data.startswith('restart'))
async def restart(callback_query: types.CallbackQuery, state: FSMContext):
    print(callback_query.from_user.username, 'restart')
    await callback_query.message.delete()
    await start(callback_query, state)


async def create_tables():
    async with engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Созданы таблицы в базе данных")


async def on_startup(bot: Bot, base_url: str):
    await bot.set_webhook(
        f"{APP_BASE_URL}/webhook",
        drop_pending_updates=True,
    )
    await create_tables()


def main():
    dp["base_url"] = APP_BASE_URL
    dp.startup.register(on_startup)

    app: web.Application = web.Application()
    app["bot"] = bot

    app.router.add_post("/payment_hook", lambda request: process_payment(request, dp.fsm.storage))
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    ).register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    web.run_app(app, host="127.0.0.1", port=5000)


if __name__ == "__main__":
    main()
