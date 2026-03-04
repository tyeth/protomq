# ProtoMQ

Dynamic MQTT Broker that speaks protobufs. Includes a web UI for inspecting
connections, decoding protobuf messages, and sending messages to connected devices.

## Get Started

1. Clone this repo
2. Run `npm i` (requires Node.js v18+)
3. Copy the environment example file: `cp .env.example.json .env.json`
4. Edit `.env.json` with the local path to your `.proto` files
5. Run `npm run import-protos` to copy and transform the proto definitions
6. Run `npm run build-web` to build the web frontend
7. Run `npm start`
8. Visit the web UI at `http://localhost:5173/`
9. Connect an MQTT client to `mqtt://localhost:1884`

## Ports

| Service    | Port |
|------------|------|
| MQTT       | 1884 |
| WebSocket  | 8888 |
| Web UI     | 5173 |

## Web UI Features

- **Clients**: Live view of connected MQTT clients
- **Subscriptions**: See what topics each client is subscribed to
- **Message Log**: All messages with protobuf decoding (newest first)
- **Protobufs**: Browse all loaded proto definitions, create and send messages via forms
- **Scripts**: Load, activate, and step through playback scripts

## Playback Scripts

Scripts are JSON files in the `scripts/` directory that define sequences of protobuf
messages to send in response to device activity. They're useful for testing device
firmware without a full backend.

### Usage

- Scripts are loaded automatically on startup but **no script is active by default**
- Activate a script via the Scripts panel in the web UI
- Once active, trigger steps fire automatically when matching messages arrive
- Sequenced steps fire after their predecessor completes (with optional delay)
- Steps can also be sent manually via the Send button in the UI

### Script Format

```json
{
  "name": "Human-readable name",
  "description": "What this script tests",
  "protoVersion": "v2",
  "steps": [
    {
      "name": "checkin-response",
      "description": "Respond to device checkin",
      "trigger": "checkin.request",
      "response": {
        "checkin": {
          "response": { "response": 1, "totalGpioPins": 20 }
        }
      }
    },
    {
      "name": "add-display",
      "description": "Configure display after checkin",
      "after": "checkin-response",
      "delay": 2000,
      "topic": "display",
      "send": {
        "display": {
          "add": { "driver": "ST7789", "name": "tft0" }
        }
      }
    }
  ]
}
```

### Step Types

**Trigger steps** execute when a matching field path exists in an incoming device message:
- `"trigger": "checkin.request"` — matches any D2B message containing `checkin.request`
- `"response": { ... }` — B2D payload sent back to the device

**Sequenced steps** execute after a named step completes:
- `"after": "step-name"` — wait for this step to complete first
- `"delay": 2000` — additional delay in milliseconds
- `"send": { ... }` — B2D payload to publish to the device

### Gotchas

- **Enum values**: Use numeric values (e.g., `"response": 1`) not string names
  (`"response": "R_OK"`). protobufjs encodes unknown string enum names as 0.
- **Topic routing**: V2 devices subscribe to a single B2D topic. The script runner
  derives the correct topic from the incoming D2B message automatically.

## Autoresponders

When no script is active (or a message doesn't match any script trigger), built-in
fallback handlers respond to common messages:

- **V2 checkin**: Automatically responds with `R_OK` and default board capabilities
- **V1 checkin**: Responds with `RESPONSE_OK` (V1 flat message format)

## Authentication

The broker accepts any credentials except specifically invalid test values
(`invalid_io_user`, `invalid_io_key`, client IDs containing `invalid`).

## Proto Import

ProtoMQ transforms `.proto` files into a JSON bundle that protobufjs can load at
runtime. Configure the source path in `.env.json`:

```json
{
  "protobufSource": "c:/path/to/your/proto/definitions"
}
```

Then run `npm run import-protos` to regenerate `protobufs/bundle.json`.
