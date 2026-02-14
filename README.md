# Multi-Agent Orchestration using LangGraph (Self-Hosted LiveKit + Agent + Frontend)

A production-ready starter to run a **self-hosted LiveKit voice assistant stack** with:
- **LiveKit server** (media + signaling)
- **Python voice agent** (STT/LLM/TTS + LangGraph orchestration)
- **Next.js frontend** (web client)

This guide covers both:
- **Local self-hosting** (for development/testing)
- **Production self-hosting** (with domain + TLS)

---

## 1) Stack Overview

Services defined in `docker-compose.prod.yml`:
- `livekit` → LiveKit server (`7880`, UDP media range)
- `agent` → Python LiveKit + LangGraph orchestrated agent (`agent/myagent.py`)
- `frontend` → Next.js app (`3000`)

Core config files:
- `docker-compose.prod.yml`
- `livekit.yaml`
- `.env` (create from `.env.example`)

Additional root files you added:
- `caddy.yaml` (TLS + L4 proxy routing)
- `egress-config.yaml` (LiveKit egress worker settings)
- `sip.yaml` (LiveKit SIP service settings)
- `dispatch.json` (SIP trunk dispatch rule payload)
- `record-twilio.json` (example room recording payload)
- `livekit-dashboard/docker-compose.yml` (self-hosted admin dashboard)

---

## 2) Multi-Agent Orchestration (LangGraph)

The agent uses a **LangGraph supervisor pattern**:
- `supervisor` node reads user metadata and chooses route
- specialist nodes generate role-specific system instructions
- LiveKit voice pipeline then uses those instructions for conversation

Supported orchestration modes:
- `general`
- `sales`
- `support`
- `technical`

Supported language routing:
- `hi` (Hindi)
- `en` (English)

Effective route examples:
- `general_hi`, `sales_hi`, `support_hi`, `technical_hi`
- `general_en`, `sales_en`, `support_en`, `technical_en`

### Metadata contract from frontend

The participant metadata can include:

```json
{
  "language": "hi",
  "voice": "sarvam",
  "mode": "support"
}
```

If `mode` is missing/invalid, it defaults to `general`.

---

## 3) Prerequisites

### For Local
- Docker Desktop (or Docker Engine + Compose v2)
- Git
- Internet access for pulling images/packages
- API keys (Deepgram/Groq/Sarvam, optionally Google)

### For Production
- Linux VPS/server with Docker + Compose v2
- Public domain/subdomain(s)
- TLS certificate (via CloudPanel/Nginx/Caddy/Traefik)
- Firewall access for required TCP/UDP ports

---

## 4) Environment Setup (Required)

1. Copy env template:

```bash
cp .env.example .env
```

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

2. Open `.env` and set real values:
- `DEEPGRAM_API_KEY`
- `GROQ_API_KEY`
- `SARVAM_API_KEY`
- `GOOGLE_API_KEY` (needed if using Gemini TTS path)

3. Keep LiveKit auth values consistent:
- `livekit.yaml` has:
  - key: `devkey`
  - secret: `secret`
- `docker-compose.prod.yml` uses the same values for agent/frontend.

If you change one, update all references.

---

## 5) Local Self-Hosting (Step-by-Step)

### Step 1: Set frontend LiveKit URL for local browser access

In `docker-compose.prod.yml`, set:

```yaml
NEXT_PUBLIC_LIVEKIT_URL=ws://localhost:7880
```

(Use `ws://` locally; no TLS expected.)

### Step 2: Start all services

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

If this is your first run after enabling LangGraph, always rebuild the agent image.

### Step 3: Verify containers

```bash
docker compose -f docker-compose.prod.yml ps
```

### Step 4: Open the app

- Frontend: `http://localhost:3000`

### Useful local commands

Tail logs:

```bash
docker compose -f docker-compose.prod.yml logs -f
```

Restart a single service:

```bash
docker compose -f docker-compose.prod.yml restart agent
```

Stop stack:

```bash
docker compose -f docker-compose.prod.yml down
```

Stop + remove volumes:

```bash
docker compose -f docker-compose.prod.yml down -v
```

---

## 6) Production Self-Hosting (Step-by-Step)

### Step 1: Prepare DNS

Point domain/subdomain records to your server IP.

Recommended pattern:
- App UI: `app.yourdomain.com` → frontend
- LiveKit WS endpoint: `agent.yourdomain.com` → LiveKit (`7880`)

### Step 2: Set frontend public LiveKit URL

In `docker-compose.prod.yml`, set:

```yaml
NEXT_PUBLIC_LIVEKIT_URL=wss://agent.yourdomain.com
```

In production this **must** be `wss://` (secure WebSocket).

### Step 3: Open firewall/ports

Minimum required:
- `80/tcp` (HTTP, for cert issuance/reverse proxy)
- `443/tcp` (HTTPS/WSS)
- `3000/tcp` (frontend upstream, can be internal-only behind proxy)
- `7880/tcp` (LiveKit signaling/WebSocket)
- `50000-50010/udp` (LiveKit RTP media)

If behind reverse proxy, expose only what your architecture needs publicly.

### Step 4: Configure reverse proxy + TLS

- Terminate TLS at your proxy (CloudPanel/Nginx/Caddy/etc.)
- Proxy frontend domain to `frontend:3000`
- Proxy LiveKit domain to `livekit:7880`
- Ensure WebSocket upgrade headers are enabled for LiveKit route

### Step 5: Deploy

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### Step 6: Validate

- App loads on `https://app.yourdomain.com`
- Browser connects to `wss://agent.yourdomain.com`
- Voice flow works (mic, STT, agent response, TTS)

---

## 7) Caddy + TURN/L4 Proxy Setup

You now have `caddy.yaml` configured to:
- automate TLS certificates for your LiveKit/TURN domains
- route `livekit.example.com` to LiveKit signaling (`localhost:7880`)
- route `turn.example.com` to TURN TLS (`localhost:5349`)

Run Caddy with your config (example):

```bash
caddy run --config ./caddy.yaml
```

Notes:
- Ensure DNS for both domains points to your server.
- Ensure ports `80/tcp` and `443/tcp` are open publicly.
- Ensure upstream local ports (`7880`, `5349`) are reachable on host.

---

## 8) SIP + Dispatch + Egress (Twilio Recording Flow)

You now have SIP/egress helper files in root:
- `sip.yaml`
- `dispatch.json`
- `record-twilio.json`
- `egress-config.yaml`

Typical flow:
1. Start LiveKit + SIP service using matching API key/secret.
2. Create/apply dispatch rule from `dispatch.json`.
3. Incoming SIP calls are dispatched to `twilio-*` rooms.
4. Room egress records audio to configured output path.

### Apply dispatch rule (CLI example)

```bash
lk sip dispatch create --file dispatch.json
```

### Trigger room egress manually (CLI/API payload reference)

Use `record-twilio.json` as the request payload model for room recording jobs.

### Egress worker config

`egress-config.yaml` contains egress API credentials, websocket URL, Redis, and worker ports. Keep these values aligned with your LiveKit deployment.

---

## 9) LiveKit Dashboard (Admin UI)

Dashboard source and compose are in `livekit-dashboard/`.

Start dashboard:

```bash
cd livekit-dashboard
docker compose up -d --build
```

Dashboard defaults from `livekit-dashboard/docker-compose.yml`:
- URL: `http://localhost:8000`
- Basic auth user: `admin` (unless overridden)
- Basic auth pass: `admin` (change in production)

Required dashboard environment values:
- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `APP_SECRET_KEY`

Important:
- Change admin credentials before production use.
- Keep dashboard on private network or protect behind VPN/IP allowlist.

---

## 10) Common Issues & Fixes

### 1. Browser connects but no audio/media
- Usually UDP ports blocked.
- Confirm `50000-50010/udp` open on host/firewall/cloud security group.

### 2. WebSocket connection fails in production
- Check `NEXT_PUBLIC_LIVEKIT_URL` uses `wss://`.
- Verify TLS cert is valid for your LiveKit domain.
- Confirm reverse proxy supports WebSocket upgrades.

### 3. Agent not joining/responding
- Check agent logs:

```bash
docker compose -f docker-compose.prod.yml logs -f agent
```

- Validate API keys in `.env`.
- Confirm LiveKit API key/secret match `livekit.yaml`.
- Confirm `langgraph` is installed inside the agent image (rebuild with `--build`).

### 4. Frontend works but token/auth errors occur
- Ensure `LIVEKIT_API_KEY` + `LIVEKIT_API_SECRET` are identical across:
  - `livekit.yaml`
  - frontend env
  - agent env

### 5. Mode routing is not applied as expected
- Ensure frontend metadata includes `mode`.
- Valid modes are `general`, `sales`, `support`, `technical`.
- Check agent logs for `LangGraph selected route:`.

### 6. SIP calls not dispatching
- Confirm SIP service is running with `sip.yaml` credentials.
- Confirm dispatch rule exists and references valid `trunk_ids`.
- Ensure SIP/RTP ports are open between provider and your host.

### 7. Dashboard cannot connect to LiveKit
- Verify `LIVEKIT_URL` in `livekit-dashboard` points to reachable endpoint.
- Confirm dashboard API key/secret match LiveKit keys.
- Check dashboard logs: `docker compose logs -f` inside `livekit-dashboard`.

---

## 11) Security Notes (Important)

- Never commit real `.env` secrets.
- Rotate any key that was exposed.
- Use strong LiveKit keys/secrets in production (not default dev values).
- Restrict server access with firewall rules and least privilege.
- Do not keep plaintext API secrets in committed YAML/JSON files.
- Protect `dispatch.json`/`sip.yaml`/`egress-config.yaml` with server-only access.

---

## 12) Project Structure

```text
voice-ai/
├─ caddy.yaml
├─ egress-config.yaml
├─ sip.yaml
├─ dispatch.json
├─ record-twilio.json
├─ docker-compose.prod.yml
├─ livekit.yaml
├─ .env.example
├─ agent/
│  ├─ Dockerfile
│  ├─ myagent.py
│  └─ requirements.txt
├─ livekit-dashboard/
│  └─ docker-compose.yml
└─ voice-assistant-frontend/
   ├─ Dockerfile
   └─ app/
```

---

## 13) Quick Start Summary

### Local
1. Copy `.env.example` → `.env`, add keys
2. Set `NEXT_PUBLIC_LIVEKIT_URL=ws://localhost:7880`
3. `docker compose -f docker-compose.prod.yml up -d --build`
4. Open `http://localhost:3000`

### Production
1. Configure DNS + TLS + reverse proxy
2. Set `NEXT_PUBLIC_LIVEKIT_URL=wss://agent.yourdomain.com`
3. Open TCP/UDP ports
4. `docker compose -f docker-compose.prod.yml up -d --build`
5. Start Caddy with `caddy.yaml`
6. (Optional) Start dashboard from `livekit-dashboard/`
7. (Optional) Apply SIP dispatch rule from `dispatch.json`
8. Validate end-to-end voice session

---

If you want, the next improvement is I can make your compose setup environment-driven (no manual URL editing between local/prod) by introducing `NEXT_PUBLIC_LIVEKIT_URL` via `.env` and a dedicated local/prod override file pair.

