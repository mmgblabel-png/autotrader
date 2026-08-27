# PayPro Webhook Research

PayPro Netherlands documents webhook support through its API 2.0. A webhook is an HTTP endpoint that receives account events, such as `payment.paid`. Webhooks can be created and managed through the PayPro dashboard or API. The creation endpoint requires a name, description, URL, and may limit event types; its response contains a webhook secret. Official documentation states that event payloads describe the resource at event creation time and recommends retrieving the latest resource through the API before acting on an event.

The published webhook guide identifies `PayPro-Signature` and `PayPro-Timestamp` headers for callback verification. The application will therefore accept conversion updates only after checking an HMAC signature against the PayPro-issued webhook secret and rejecting stale timestamps and replayed delivery identifiers. Raw callback payloads and customer data remain private; the public farm snapshot exposes only aggregate conversion count, sanitized campaign identity, attribution labels, and conversion freshness.

## Sources

1. [PayPro Developers](https://www.paypro.nl/en/developers/)
2. [PayPro Webhooks](https://docs.paypro.nl/reference/api/webhooks)
3. [Create a PayPro Webhook](https://docs.paypro.nl/reference/api/webhooks/createwebhook)
4. [PayPro Events](https://docs.paypro.nl/reference/api/events)
5. [PayPro Webhook Verification](https://docs.paypro.nl/reference/webhooks)
