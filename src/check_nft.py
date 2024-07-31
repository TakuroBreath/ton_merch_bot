from pytonapi import Tonapi
from pytoniq_core import Address

from src import config

tonapi = Tonapi(api_key=config.TON_API_KEY)


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
