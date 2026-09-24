# Bitvavo implementation sources

The Bitvavo adapter follows the official Bitvavo documentation:

- [Get started](https://docs.bitvavo.com/docs/get-started/): create API keys, enable 2FA, use IP whitelisting, grant only View access and Trade digital assets, and do not grant Withdraw digital assets.
- [REST API authentication](https://docs.bitvavo.com/docs/rest-api/introduction/): send `Bitvavo-Access-Key`, millisecond `Bitvavo-Access-Timestamp`, `Bitvavo-Access-Signature` as HMAC-SHA256 over `timestamp + method + /v2 + path + body`, and an optional access window.
- [Create order](https://docs.bitvavo.com/docs/rest-api/create-order/): `POST /v2/order` with `market`, `side`, `orderType`, `operatorId`, `clientOrderId`, `amount`, and `price` as appropriate. EUR market example: `BTC-EUR`.
- [Official Python wrapper](https://github.com/bitvavo/python-bitvavo-api): reference wrapper and permission guidance. The implementation here uses the documented REST signing directly to keep the safety gates and dry-run behavior explicit.

The adapter remains `BITVAVO_DRY_RUN=true` and `EXECUTION_MODE=shadow` by default. It does not implement withdrawals.
