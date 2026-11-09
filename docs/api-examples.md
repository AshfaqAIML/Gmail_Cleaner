# API examples

Base URL: `http://127.0.0.1:8000`

Interactive API docs: `/docs`

## Preview sender cleanup

`POST /api/v1/commands`

```json
{
  "command": "preview emails from Facebook and Zoom older than 90 days"
}
```

The response has `status: "pending_confirmation"`, a `preview_id`, a Gmail query, the exact selected sender addresses and message metadata. It does not change Gmail.

## Confirm the preview

`POST /api/v1/actions/confirm`

```json
{
  "preview_id": "the-id-returned-by-the-preview-call",
  "confirm": true
}
```

Set `confirm` to `false` to cancel. Confirmation is valid only once and only until the expiry time.

## Add a sender

`POST /api/v1/senders`

```json
{
  "name": "LinkedIn",
  "email": "notifications@linkedin.com"
}
```

## List senders

`GET /api/v1/senders`

## Remove a sender

`DELETE /api/v1/senders/LinkedIn`

## Recent preview history

`GET /api/v1/history?limit=50`

## Optional bearer token

When `API_BEARER_TOKEN` is set, include:

```http
Authorization: Bearer YOUR_SECRET_TOKEN
```

The `/health` endpoint remains public. For local-only development the API can be run without a token, but it must be bound to `127.0.0.1`.
