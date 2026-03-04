# Experimental Plan: Interactive Bot + Cloud Runtime

## Branch
- `exp/interactive-cloud-lab`

## Direction 1: Two-way Interaction

### Option A: Telegram Bot
- Pros:
  - Supports command-style workflows (`/today`, `/tasks`, `/snooze 2h`, `/done`).
  - Easy webhook/polling model.
  - Good for private one-on-one interaction.
- Cons:
  - You need to move daily push channel from Pushover to Telegram or keep dual channels.
  - New bot setup and chat-id binding flow needed.

### Option B: Discord Bot (recommended first if you already run OpenClaw bot)
- Pros:
  - You already have a server and a bot runtime.
  - Thread/channel based collaboration is easier for experiments.
  - Slash commands and button interactions are mature.
- Cons:
  - Multi-user permission/rate-limit model is more complex.
  - DM vs guild command scopes need explicit design.

### MVP Scope (2-4 days)
1. Add command endpoints:
   - `/today`
   - `/tasks`
   - `/snooze <hours>`
   - `/done <task_id>`
2. Persist task state:
   - `snoozed_until`
   - `done_at`
3. Add "draft reply" command for immediate mails:
   - `/draft <mail_id>` generates a reply draft with LLM.
4. Keep current digest/push flow unchanged as fallback.

## Direction 2: 24x7 Runtime on Free Tier

### Oracle Cloud Free Tier (validated)
- Oracle states there is an Always Free tier and a free trial tier.
- Common Always Free resources include Ampere A1 compute, block storage, and object storage (with region/resource availability caveats).
- Practical risk: capacity is not guaranteed in all regions; instance creation may fail depending on quota and region pressure.

### Suggested deployment architecture
1. One lightweight VM (Ubuntu) running:
   - FastAPI app (uvicorn + systemd)
   - reverse proxy (Caddy or Nginx)
2. Persist local data files in a fixed directory:
   - `data/ms_token.json`
   - `data/run_state.json`
   - LLM/cache JSON files
3. Add process-level reliability:
   - systemd restart policy
   - health endpoint probe + startup logs

## Recommendation
1. Start with Discord integration first (lower adoption cost for your current workflow).
2. In parallel, prepare Oracle deployment script (or fallback to Railway/Fly if Oracle capacity unavailable).
3. Keep Telegram as second transport adapter after command model is stable.

## Immediate Next Tasks
1. Define bot command contract and response schema.
2. Add a `BotAdapter` abstraction layer (`DiscordAdapter`, `TelegramAdapter`).
3. Add persistence model for snooze/done state and mail draft context.
4. Add one-click deploy script for VM bootstrap.
