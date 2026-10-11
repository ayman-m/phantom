# Cortex XSIAM — authentication

Cortex XSIAM's REST API uses two auth modes. The Phantom connector supports
both via per-instance config; `_xsiam_client.py` selects based on the
instance's `auth_mode` field.

## Standard (basic) auth

Three headers per request:

```http
Authorization: <API_KEY>
x-xdr-auth-id: <API_KEY_ID>
Content-Type: application/json
```

- `API_KEY` is the value the operator pastes when generating an "Advanced API Key" set to "Standard" security level
- `API_KEY_ID` is the integer ID XDR assigns to that key

## Advanced auth (HMAC over nonce + timestamp)

Used when the API key is "Advanced" security level. Headers per request:

```http
Authorization: <hex(sha256(API_KEY + nonce + timestamp))>
x-xdr-auth-id: <API_KEY_ID>
x-xdr-nonce: <random 64-char string>
x-xdr-timestamp: <unix-millis>
Content-Type: application/json
```

Phantom's `_xsiam_client.py` generates the nonce + timestamp per request and
computes the SHA-256. Operators never paste plain API keys into the agent;
keys live in the `SecretStore` and the agent only sees the per-instance
handle (`instance_id`).

## Base URL

```
https://api-{fqdn}/public_api/v1/{api_name}/{call_name}/
```

`fqdn` is the operator-visible XDR tenant FQDN (e.g. `acme.xdr.us.paloaltonetworks.com`).
`api_name` matches the category (incidents/alerts/endpoints/etc.).
`call_name` is the per-endpoint suffix (list, get_extra_data, isolate, etc.).
