import sys
import logging
import asyncio
import time
from io import BytesIO
from pyexpat.errors import messages

import qrcode

import pytonconnect.exceptions
from pytonapi import Tonapi
from pytonapi.utils import nano_to_amount
from pytoniq_core import Address
from pytonconnect import TonConnect

import config
from messages import get_comment_message
from connector import get_connector

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InputMediaPhoto, InputFile, FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils import markdown

logger = logging.getLogger(__file__)

dp = Dispatcher()
bot = Bot(config.TOKEN)

TON_API_KEY = 'AEGOUR3VZ55ERHAAAAAMTQ2R57ID43WZOBVAJLBOSMKRV52G26CT7PLHQG6NOOTU432NYVQ'
tonapi = Tonapi(api_key=TON_API_KEY)


@dp.message(CommandStart())
async def command_start_handler(message: Message):
    chat_id = message.chat.id
    connector = get_connector(chat_id)
    connected = await connector.restore_connection()

    mk_b = InlineKeyboardBuilder()
    if connected:
        mk_b.button(text='Оплатить', callback_data='pay')
        mk_b.button(text='Предпросмотр', callback_data='preview')
        mk_b.button(text='Отключить кошелек', callback_data='disconnect')
        await message.answer(text='You are already connected!', reply_markup=mk_b.as_markup())

    else:
        wallets_list = TonConnect.get_wallets()
        for wallet in wallets_list:
            mk_b.button(text=wallet['name'], callback_data=f'connect:{wallet["name"]}')
        mk_b.adjust(1, )
        await message.answer(text='Выбери кошелек для привязки', reply_markup=mk_b.as_markup())


@dp.message(Command('preview'))
async def preview(message: Message):
    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Оплатить', callback_data='pay')
    photo = FSInputFile("merch.jpg")
    await message.answer_photo(photo=photo, caption="вот те шмотка", reply_markup=mk_b.as_markup())


async def check_nft(address):
    discount_1 = False
    discount_2 = False

    account_id = Address(address).to_str(is_bounceable=True)
    result = tonapi.accounts.get_nfts(account_id=account_id, limit=100)

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
        return 1
    elif discount_2:
        return 2
    else:
        return 0


@dp.message(Command('pay'))
async def pay(message: Message):
    connector = get_connector(message.chat.id)
    connected = await connector.restore_connection()
    if not connected:
        await message.answer('Подключите кошелек')
        return

    address = connector.account.address
    address = Address(address).to_str(is_bounceable=False)
    nft = await asyncio.wait_for(check_nft(address), timeout=200)
    amount = 7.0

    if nft == 1:
        await message.answer(f"У вас есть NFT 1 коллекции. Стоимость футболки для вас: {amount-1.4} TON")
        amount -= 1.4
    elif nft == 2:
        await message.answer(f"У вас есть NFT 2 коллекции. Стоимость футболки для вас: {amount - 0.7} TON")
        amount -= 0.7
    else:
        await message.answer(f"Для получения скидки купите NFT. Стоимость футболки для вас: {amount} TON")

    transaction = {
        'valid_until': int(time.time() + 3600),
        'messages': [
            get_comment_message(
                destination_address=f'{config.ACCOUNT_ID}',
                amount=int(0.01 * 10 ** 9),
                comment=f'{message.chat.id}'
            )
        ]
    }

    await message.answer(text='Подтвердите платеж в приложении кошелька!')
    try:
        send_task = asyncio.wait_for(connector.send_transaction(
            transaction=transaction
        ), 300)
        scan_task = asyncio.create_task(scanner())
        await asyncio.gather(send_task, scan_task)
    except asyncio.TimeoutError:
        await message.answer(text='Время для платежа вышло')
    except pytonconnect.exceptions.UserRejectsError:
        await message.answer(text='Вы отмениили платеж')
    except Exception as e:
        await message.answer(text=f'Неизвестная ошибка: {e}')


async def scanner():
    for i in range(180):
        await asyncio.sleep(1)
        result = tonapi.blockchain.get_account_transactions(account_id=config.ACCOUNT_ID, limit=1000)
        txs = result.transactions
        tx = txs[0]
        print(tx)
        if nano_to_amount(tx.in_msg.value) > 0:
            if tx.in_msg.decoded_op_name == "text_comment":
                telegram_id = tx.in_msg.decoded_body['text']
                await bot.send_message(chat_id=telegram_id, text="Платеж принят! Пожалуйста, отправьте ваш адрес.")
                break


async def connect_wallet(message: Message, wallet_name: str):
    connector = get_connector(message.chat.id)

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

    await message.answer_photo(photo=file, caption='Подключите кошелек в течение 3-х минут', reply_markup=mk_b.as_markup())

    mk_b = InlineKeyboardBuilder()
    mk_b.button(text='Start', callback_data='start')

    for i in range(1, 180):
        await asyncio.sleep(1)
        if connector.connected:
            if connector.account.address:
                wallet_address = connector.account.address
                wallet_address = Address(wallet_address).to_str(is_bounceable=False)
                await message.answer(f'Вы подключили кошелек: {markdown.blockquote(wallet_address)}', reply_markup=mk_b.as_markup())
                logger.info(f'Connected with address: {wallet_address}')
            return

    await message.answer(f'Время для подключения вышло!', reply_markup=mk_b.as_markup())


async def disconnect_wallet(message: Message):
    connector = get_connector(message.chat.id)
    prev = await message.answer('Идет отвязка кошелька. Это может занять время...')
    await connector.restore_connection()
    await connector.disconnect()
    await bot.delete_message(message.chat.id, prev.message_id)
    await message.answer('Вы отключили кошелек')


@dp.callback_query(lambda call: True)
async def main_callback_handler(call: CallbackQuery):
    await call.answer()
    message = call.message
    data = call.data
    if data == "start":
        await command_start_handler(message)
    elif data == "pay":
        await pay(message)
    elif data == 'preview':
        await preview(message)
    elif data == 'disconnect':
        await disconnect_wallet(message)
    else:
        data = data.split(':')
        if data[0] == 'connect':
            await connect_wallet(message, data[1])


async def main() -> None:
    await bot.delete_webhook(drop_pending_updates=True)  # skip_updates = True
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())