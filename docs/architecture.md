# Architecture and safety boundaries

## Design principle

The language model is an intent parser, not an autonomous Gmail operator. It returns a strict schema describing a supported user intent. It receives neither OAuth credentials nor Gmail API tools.

## Trust boundaries

- **Untrusted input:** user commands and model output.
- **Validation boundary:** Pydantic schema validation, sender registry resolution, email-address validation, and checking that a literal sender email returned by the model was present in the user's command.
- **Gmail boundary:** application-generated sender/date query only; no model-generated Gmail query is accepted.
- **Action boundary:** an expiring preview ID is created after the matching messages are retrieved. A separate confirmation request atomically claims the preview before any Trash operation.

## Data flow

1. Parse the command into `ParsedCommand`.
2. Resolve sender tokens to exact saved addresses or literal addresses typed by the user.
3. Construct a Gmail query using the query builder.
4. List message IDs with pagination and `includeSpamTrash=false`.
5. Fetch only `From`, `Subject`, and `Date` headers for each result.
6. Verify the parsed From address exactly matches a requested sender address.
7. Reject searches that exceed `MAX_MESSAGES_PER_PREVIEW`.
8. Store the selected message IDs and preview metadata with an expiry.
9. On confirmation, atomically transition `pending` to `executing`, then call Gmail `messages.trash` for each stored ID.
10. Record `completed`, `partially_completed`, `failed`, or `cancelled`.

## State transitions

```text
pending -> executing -> completed
                    -> partially_completed
                    -> failed
pending -> cancelled
pending -> expired
```

A preview is single-use. The database update used to claim a preview is conditional on the row still being pending and unexpired, reducing the chance that concurrent requests process the same preview twice.

## Deliberate limitations

- A preview is a snapshot. Gmail can change between preview and confirmation. The initial release uses a short expiry and re-fetches each message's From header immediately before Trash, checking it against the original sender allow-list.
- A crash while a batch is executing can leave a preview in `executing`. The user should inspect Gmail before retrying. A future release can persist per-message progress and add recovery tooling.
- SQLite is suitable for a single-user local installation, not a multi-user hosted deployment.
- The API must remain on localhost unless authentication, HTTPS, rate limiting, CSRF considerations for browser clients, and deployment controls are added.
