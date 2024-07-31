import asyncio
import logging
import sys
import time
from io import BytesIO
import openpyxl

import pandas as pd
import pytonconnect.exceptions
import qrcode
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.fsm.state import StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, BufferedInputFile, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pytonapi import Tonapi
from pytonapi.utils import nano_to_amount
from pytonconnect import TonConnect
from pytoniq_core import Address

import config
from check_nft import check_nft
from connector import get_connector
from db import *
from messages import get_comment_message

logger = logging.getLogger(__file__)

ADMIN_ID = config.ADMIN_ID


class Form(StatesGroup):
    waiting_for_address = State()
    waiting_for_new_address = State()


# Инициализация бота и диспетчера
storage = MemoryStorage()
dp = Dispatcher()
bot = Bot(config.TOKEN)

tonapi = Tonapi(api_key=config.TON_API_KEY)


@dp.callback_query(lambda call: True)
async def main_callback_handler(call: CallbackQuery):
    await call.answer()
    message = call.message
    connector = await connect(message)
    data = call.data
    if data == "start":
        await command_start_handler(message, connector)
    elif data == 'preview':
        await preview(message)
    elif data == 'disconnect':
        await disconnect_wallet(message, connector)
    else:
        data = data.split(':')
        if data[0] == 'connect':
            await connect_wallet(message, data[1], connector)
        elif data[0] == 'buy':
            size = data[1]
            update_user_size(message.chat.id, size)
            await buy(message, size, connector)
        elif data[0] == 'pay':
            await pay(message, data[1], connector)


@dp.message(CommandStart())
async def command_start_handler(message: Message, connector: TonConnect = None):
    if connector is None:
        connector = get_connector(message.chat.id)
    connected = await connector.restore_connection()

    telegram_id = message.from_user.id
    username = message.from_user.username
    add_user(telegram_id, username)

    mk_b = InlineKeyboardBuilder()
    if connected:
        mk_b.button(text='Предпросмотр', callback_data='preview')
        mk_b.button(text='Отключить кошелек', callback_data='disconnect')
        await message.answer(text='Выберите действие:', reply_markup=mk_b.as_markup())
    else:
        wallets_list = TonConnect.get_wallets()
        for wallet in wallets_list:
            mk_b.button(text=wallet['name'], callback_data=f'connect:{wallet["name"]}')
        mk_b.adjust(1, )
        msg = await message.answer(text='Выберите кошелек для привязки', reply_markup=mk_b.as_markup())
        await asyncio.create_task(delete_message(msg, 120))


async def connect_wallet(message: Message, wallet_name: str, connector: TonConnect):
    wallets_list = connector.get_wallets()
    wallet = None

    for w in wallets_list:
        if w['name'] == wallet_name:
            wallet = w

    if wallet is None:
        raise Exception(f'Неизвестный кошелек: {wallet_name}')

    generated_url = await connector.connect(wallet)

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Подключить', url=generated_url)

    img = qrcode.make(generated_url)
    stream = BytesIO()
    img.save(stream)
    file = BufferedInputFile(file=stream.getvalue(), filename='qrcode')

    prev = await message.answer_photo(photo=file, caption='Подключите кошелек в течение 3-х минут',
                                      reply_markup=mk_b.as_markup())

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Начать', callback_data='start')

    for i in range(1, 180):
        await asyncio.sleep(1)
        if connector.connected:
            if connector.account.address:
                wallet_address = connector.account.address
                wallet_address = Address(wallet_address).to_str(is_bounceable=False)
                update_wallet_address(message.chat.id, wallet_address)
                await message.answer(f'Вы подключили кошелек: {wallet_address}', reply_markup=mk_b.as_markup())
                await bot.delete_message(message.chat.id, prev.message_id)
                logger.info(f'Подключенный кошелек: {wallet_address}')
            return

    await message.answer(f'Время для подключения вышло!', reply_markup=mk_b.as_markup())
    await bot.delete_message(message.chat.id, prev.message_id)


async def disconnect_wallet(message: Message, connector: TonConnect):
    prev = await message.answer('Идет отвязка кошелька. Это может занять время...')
    await connector.restore_connection()
    try:
        await connector.disconnect()
        await bot.delete_message(message.chat.id, prev.message_id)
    except Exception as e:
        await message.answer('Вы отключили кошелек')
        await bot.delete_message(message.chat.id, prev.message_id)


@dp.message(Command(commands='preview'))
async def preview(message: Message):
    conn = sqlite3.connect('../database/inventory.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM inventory')
    inventory = cursor.fetchall()
    conn.close()

    inventory_dict = {item[0]: item[1] for item in inventory}

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Купить M', callback_data='buy:M')
    mk_b.button(text='Купить L', callback_data='buy:L')

    photo = FSInputFile("../media/merch.jpg")
    m_count = inventory_dict.get('M', 0)
    l_count = inventory_dict.get('L', 0)
    caption = (f"Футболка oversize\n\n"
               f"Доступно для покупки\n"
               f"Размер М: {m_count} шт.\n"
               f'Размер L: {l_count} шт.')

    await message.answer_photo(photo=photo, caption=caption, reply_markup=mk_b.as_markup())


async def buy(message: Message, size: str, connector: TonConnect):
    connected = await connector.restore_connection()
    if not connected:
        mk_b = InlineKeyboardBuilder()
        mk_b.button(text='Подключить', callback_data='start')
        await message.answer('Подключите кошелек', reply_markup=mk_b.as_markup())
        return

    address = connector.account.address
    address = Address(address).to_str(is_bounceable=False)
    nft = await asyncio.wait_for(check_nft(address), timeout=200)

    # Определение цены футболки и применения скидок
    base_amount = config.BASE_AMOUNT
    if nft == 1:
        amount = round(base_amount - base_amount * 0.2, 5)
        await message.answer(f"У вас есть NFT первой коллекции. Стоимость футболки для вас: {amount} TON")
    elif nft == 2:
        amount = round(base_amount - base_amount * 0.1, 5)
        await message.answer(f"У вас есть NFT второй коллекции. Стоимость футболки для вас: {amount} TON")
    else:
        amount = base_amount
        await message.answer(f"Для получения скидки купите NFT. Стоимость футболки для вас: {amount} TON")

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Оплатить', callback_data=f'pay:{amount}')

    # Проверка наличия футболок в базе данных
    conn = sqlite3.connect('../database/inventory.db')
    cursor = conn.cursor()
    cursor.execute('SELECT quantity FROM inventory WHERE size = ?', (size,))
    quantity = cursor.fetchone()
    conn.close()

    if quantity and quantity[0] > 0:
        # Если футболка есть в наличии, то уменьшаем количество
        update_inventory(size, quantity[0] - 1)
        await message.answer(f"Футболка размера {size} доступна. {quantity[0] - 1} шт. осталось.")
        await message.answer("Подтвердите платеж в кошельке!", reply_markup=mk_b.as_markup())
    else:
        await message.answer(f"Футболки размера {size} закончились.")


async def pay(message: Message, amount: str, connector: TonConnect):
    connected = await connector.restore_connection()
    amount = float(amount)
    if not connected:
        mk_b = InlineKeyboardBuilder()
        mk_b.button(text='Подключить', callback_data='start')
        await message.answer('Подключите кошелек', reply_markup=mk_b.as_markup())
        return
    transaction = {
        'valid_until': int(time.time() + 3600),
        'messages': [
            get_comment_message(
                destination_address=f'{config.ACCOUNT_ID}',
                amount=int(amount * 10 ** 9),
                comment=f'{message.chat.id}'
            )
        ]
    }

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Повторить', callback_data='pay')

    msg = await message.answer(text='Подтвердите платеж в приложении кошелька!')
    delete = asyncio.create_task(delete_message(msg, 120))
    try:
        send_task = asyncio.wait_for(connector.send_transaction(
            transaction=transaction
        ), 300)
        await asyncio.gather(send_task, delete)
    # except asyncio.TimeoutError:
    #     msg = await message.answer(text='Время для платежа вышло', reply_markup=mk_b.as_markup())
    #     await asyncio.create_task(delete_message(msg, 120))
    # except pytonconnect.exceptions.UserRejectsError:
    #     await message.answer(text='Вы отменили платеж', reply_markup=mk_b.as_markup())
    #     await asyncio.create_task(delete_message(msg, 120))
    except Exception as e:
        pass
        # await message.answer(text=f'Неизвестная ошибка: {e}, напишите @MaxSmurffy с текстом этой ошибки.')


@dp.message(Command('address'))
async def address_command_handler(message: Message, state: FSMContext):
    telegram_id = message.from_user.id

    # Проверка, что пользователь оплатил заказ
    conn = sqlite3.connect('../database/users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT payment_status FROM users WHERE telegram_id = ?', (telegram_id,))
    result = cursor.fetchone()
    conn.close()

    if result and result[0] == 'paid':
        # Устанавливаем состояние ожидания адреса
        await state.set_state(Form.waiting_for_address)
        await message.answer(f"Пожалуйста, введите ваш адрес для доставки в следующем формате:\nФИО\nРегион\nГород\nУлица\nДом\nКвартира\nИндекс\nНомер телефона")
    else:
        await message.answer('Вы не оплатили заказ. Пожалуйста, сначала оплатите заказ.')


@dp.message(Form.waiting_for_address)
async def process_address(message: Message, state: FSMContext):
    address = message.text
    telegram_id = message.from_user.id

    update_user_address(telegram_id, address)

    conn = sqlite3.connect('../database/users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT username FROM users WHERE telegram_id = ?', (telegram_id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        username = user[0]
        conn = sqlite3.connect('../database/users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT size FROM users WHERE telegram_id = ?', (telegram_id,))
        size = cursor.fetchone()[0]
        cursor.execute('''
            UPDATE users SET payment_status = ? WHERE telegram_id = ?
            ''', ('added', telegram_id))
        conn.commit()
        conn.close()

        add_order(telegram_id, username, address, size)

        await message.answer(f"Ваш адрес: {address} был сохранен.\n\nЧтобы изменить адрес, введите /change_address")
        await bot.send_message(ADMIN_ID,
                               f"Пользователь @{username} оплатил заказ. Он заказал футболку с размером {size}. Его адрес: {address}")
    else:
        await message.answer(f'Ваш адрес: {address} был сохранен, но произошла ошибка при отправке уведомления админу.')

    # Завершаем состояние
    await state.clear()


@dp.message(Command(commands='change_address'))
async def change_address(message: Message, state: FSMContext):
    telegram_id = message.from_user.id

    conn = sqlite3.connect('../database/orders.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM orders WHERE telegram_id = ?', (telegram_id,))
    order_count = cursor.fetchone()[0]
    conn.close()

    if order_count > 0:
        await state.set_state(Form.waiting_for_new_address)
        await message.answer("Введите новый адрес для доставки:")
    else:
        await message.answer("У вас нет заказов. Вы не можете изменить адрес.")


@dp.message(Form.waiting_for_new_address)
async def process_new_address(message: Message, state: FSMContext):
    new_address = message.text
    telegram_id = message.from_user.id

    update_user_address(telegram_id, new_address)
    update_order_address(telegram_id, new_address)

    await message.answer(f'Ваш новый адрес: {new_address} был сохранен.')

    conn = sqlite3.connect('../database/users.db')
    cursor = conn.cursor()
    cursor.execute('SELECT username FROM users WHERE telegram_id = ?', (telegram_id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        username = user[0]
        await bot.send_message(ADMIN_ID,
                               f"Пользователь @{username} изменил адрес на: {new_address}")
    else:
        await message.answer(f'Ваш новый адрес: {new_address} был сохранен, но произошла ошибка при отправке уведомления админу.')

    # Завершаем состояние
    await state.clear()


@dp.message(Command(commands='export_db'))
async def export_db(message: Message):
    if str(message.from_user.id) != ADMIN_ID:
        await message.answer('У вас нет прав для выполнения этой команды.')
        return

    conn_users = sqlite3.connect('../database/users.db')
    df_users = pd.read_sql_query('SELECT * FROM users', conn_users)
    conn_users.close()

    conn_transactions = sqlite3.connect('../database/transactions.db')
    df_transactions = pd.read_sql_query('SELECT * FROM transactions', conn_transactions)
    conn_transactions.close()

    conn_inventory = sqlite3.connect('../database/inventory.db')
    df_inventory = pd.read_sql_query('SELECT * FROM inventory', conn_inventory)
    conn_inventory.close()

    conn_orders = sqlite3.connect('../database/orders.db')
    df_orders = pd.read_sql_query('SELECT * FROM orders', conn_orders)
    conn_orders.close()

    with pd.ExcelWriter('databases_export.xlsx') as writer:
        df_users.to_excel(writer, sheet_name='Users', index=False)
        df_transactions.to_excel(writer, sheet_name='Transactions', index=False)
        df_inventory.to_excel(writer, sheet_name='Inventory', index=False)
        df_orders.to_excel(writer, sheet_name='Orders', index=False)

    file = FSInputFile('databases_export.xlsx')
    await bot.send_document(chat_id=message.chat.id, document=file)


async def scan():
    while True:
        await asyncio.sleep(5)
        try:
            result = tonapi.blockchain.get_account_transactions(account_id=config.ACCOUNT_ID, limit=1000)
            txs = result.transactions

            for tx in txs:
                tx_hash = tx.hash
                comment = tx.in_msg.decoded_body['text']

                # Проверка, есть ли уже такая транзакция в базе данных
                conn = sqlite3.connect('../database/transactions.db')
                cursor = conn.cursor()
                cursor.execute('''
                        SELECT * FROM transactions WHERE hash = ?
                        ''', (tx_hash,))
                existing_tx = cursor.fetchone()
                conn.close()

                if existing_tx:
                    continue  # Если транзакция уже существует, пропустить

                # Если транзакция новая, добавить ее в базу данных
                add_transaction(tx_hash, comment)

                if comment:
                    # Если комментарий содержит telegram_id, то отправить сообщение и обновить флаг
                    telegram_id = comment
                    amount = nano_to_amount(tx.in_msg.value)
                    update_user_payment_status(telegram_id, 'paid', amount)
                    update_transaction_flag(tx_hash)
                    await bot.send_message(chat_id=telegram_id,
                                           text="Платеж принят! Пожалуйста, отправьте ваш адрес. Для этого используйте команду /address. Вводите максимально полный адрес.")

        except Exception as e:
            logger.error(f"Ошибка сканирования: {e}")


async def delete_message(message: Message, sleep_time: int = 60):
    await asyncio.sleep(sleep_time)
    await message.delete()


async def connect(message):
    chat_id = message.chat.id
    connector = get_connector(chat_id)
    return connector


async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.gather(dp.start_polling(bot), scan())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    create_databases()
    asyncio.run(main())
