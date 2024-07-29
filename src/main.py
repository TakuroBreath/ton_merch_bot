import sys
import logging
import asyncio
import time
import sqlite3
from io import BytesIO
import qrcode

import pytonconnect.exceptions
from pytoniq_core import Address
from pytonconnect import TonConnect

import config
from messages import get_comment_message
from connector import get_connector

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from pytonapi import Tonapi
from pytonapi.utils import nano_to_amount

logger = logging.getLogger(__file__)

dp = Dispatcher()
bot = Bot(config.TOKEN)

TON_API_KEY = 'AEGOUR3VZ55ERHAAAAAMTQ2R57ID43WZOBVAJLBOSMKRV52G26CT7PLHQG6NOOTU432NYVQ'
tonapi = Tonapi(api_key=TON_API_KEY, is_testnet=config.IS_TESTNET)

# Подключение к базе данных
conn = sqlite3.connect('database.db')
cursor = conn.cursor()

# Создание таблицы
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    wallet_address TEXT,
    payment_status TEXT,
    amount_sent REAL,
    address TEXT
)
''')
conn.commit()


# Функция для добавления пользователя в базу данных
def add_user_to_db(telegram_id, username, wallet_address, payment_status='Pending', amount_sent=0.0, address=None):
    cursor.execute('''
    INSERT OR REPLACE INTO users (telegram_id, username, wallet_address, payment_status, amount_sent, address)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (telegram_id, username, wallet_address, payment_status, amount_sent, address))
    conn.commit()


# Функция для обновления статуса платежа и суммы
def update_payment_status(telegram_id, payment_status, amount_sent):
    cursor.execute('''
    UPDATE users
    SET payment_status = ?, amount_sent = ?
    WHERE telegram_id = ?
    ''', (payment_status, amount_sent, telegram_id))
    conn.commit()


# Функция для обновления адреса
def update_address(telegram_id, address):
    cursor.execute('''
    UPDATE users
    SET address = ?
    WHERE telegram_id = ?
    ''', (address, telegram_id))
    conn.commit()


@dp.message(CommandStart())
async def command_start_handler(message: Message):
    chat_id = message.chat.id
    connector = get_connector(chat_id)
    connected = await connector.restore_connection()

    mk_b = InlineKeyboardBuilder()
    if connected:
        # mk_b.button(text='Send Transaction', callback_data='send_tr')
        mk_b.button(text='Disconnect', callback_data='disconnect')
        await message.answer(text='You are already connected!', reply_markup=mk_b.as_markup())

    else:
        wallets_list = TonConnect.get_wallets()
        for wallet in wallets_list:
            mk_b.button(text=wallet['name'], callback_data=f'connect:{wallet["name"]}')
        mk_b.adjust(1, )
        await message.answer(text='Choose wallet to connect', reply_markup=mk_b.as_markup())


async def check_nft_and_send_transaction(message: Message, wallet_address: str):
    account_id = Address(wallet_address).to_str(is_bounceable=True)
    result = tonapi.accounts.get_nfts(account_id=account_id, limit=100)

    discount_1 = False
    discount_2 = False

    for nft in result.nft_items:
        if nft.collection:
            if nft.collection.address.to_userfriendly(
                    is_bounceable=True) == "EQAzlVUwnQKBSJeyyP-733Xp44tnZDg_b_dzMqZEO-z58yeC":
                discount_1 = True
                break
            if nft.collection.address.to_userfriendly(
                    is_bounceable=True) == "EQCGYlzlIXsUs9lm3LdMcqHicSyl_5QDEn6QR3xdRcjW698K":
                discount_2 = True

    if discount_1:
        amount = 5.6  # 20% скидка
    elif discount_2:
        amount = 6.3  # 10% скидка
    else:
        amount = 7.0  # без скидки

    connector = get_connector(message.chat.id)
    connected = await connector.restore_connection()
    if not connected:
        await message.answer('Connect wallet first!')
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

    # Добавление пользователя в базу данных
    add_user_to_db(message.chat.id, message.from_user.username, wallet_address)

    await message.answer(text='Approve transaction in your wallet app!')
    try:
        await asyncio.wait_for(connector.send_transaction(transaction=transaction), 300)
    except asyncio.TimeoutError:
        await message.answer(text='Timeout error!')
    except pytonconnect.exceptions.UserRejectsError:
        await message.answer(text='You rejected the transaction!')
    except Exception as e:
        await message.answer(text=f'Unknown error: {e}')


async def connect_wallet(message: Message, wallet_name: str):
    connector = get_connector(message.chat.id)

    wallets_list = connector.get_wallets()
    wallet = None

    for w in wallets_list:
        if w['name'] == wallet_name:
            wallet = w

    if wallet is None:
        raise Exception(f'Unknown wallet: {wallet_name}')
    print("Url is coming")
    generated_url = await connector.connect(wallet)

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Connect', url=generated_url)

    img = qrcode.make(generated_url)
    stream = BytesIO()
    img.save(stream)
    file = BufferedInputFile(file=stream.getvalue(), filename='qrcode')

    await message.answer_photo(photo=file, caption='Connect wallet within 3 minutes', reply_markup=mk_b.as_markup())

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Start', callback_data='start')

    for i in range(1, 180):
        await asyncio.sleep(1)
        if connector.connected:
            if connector.account.address:
                wallet_address = connector.account.address
                wallet_address_str = Address(wallet_address).to_str(is_bounceable=False)
                await message.answer(f'You are connected with address {wallet_address_str}',
                                     reply_markup=mk_b.as_markup())
                logger.info(f'Connected with address: {wallet_address_str}')
                await check_nft_and_send_transaction(message, wallet_address_str)
            return

    await message.answer(f'Timeout error!', reply_markup=mk_b.as_markup())


async def disconnect_wallet(message: Message):
    connector = get_connector(message.chat.id)
    await connector.restore_connection()
    await connector.disconnect()
    await message.answer('You have been successfully disconnected!')


@dp.callback_query(lambda call: True)
async def main_callback_handler(call: CallbackQuery):
    await call.answer()
    message = call.message
    data = call.data
    if data == "start":
        await command_start_handler(message)
    elif data == 'disconnect':
        await disconnect_wallet(message)
    else:
        data = data.split(':')
        if data[0] == 'connect':
            await connect_wallet(message, data[1])


async def scan_wallet():
    while True:
        result = tonapi.blockchain.get_account_transactions(account_id=config.ACCOUNT_ID, limit=1000)
        txs = result.transactions
        for tx in txs:
            if nano_to_amount(tx.in_msg.value) > 5:
                if tx.in_msg.decoded_op_name == "text_comment":
                    telegram_id = tx.in_msg.decoded_body['text'].replace("telegram_id: ", "")
                    update_payment_status(telegram_id, 'Paid', nano_to_amount(tx.in_msg.value))
                    await bot.send_message(telegram_id, "Платеж принят! Пожалуйста, отправьте ваш адрес.")
        await asyncio.sleep(30)  # сканировать кошелек каждые 30 секунд


async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)  # skip_updates = True
    await dp.start_polling(bot)
    await asyncio.create_task(scan_wallet())  # запуск сканера кошелька


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
