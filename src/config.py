from os import environ as env

from dotenv import load_dotenv
load_dotenv()

TOKEN = env['TOKEN']
MANIFEST_URL = env['MANIFEST_URL']
IS_TESTNET = True

if IS_TESTNET:
    ACCOUNT_ID = env['TEST_ACCOUNT_ID']
else:
    ACCOUNT_ID = env['ACCOUNT_ID']

