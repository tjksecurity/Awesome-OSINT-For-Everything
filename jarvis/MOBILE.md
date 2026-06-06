# EVA on your phone

Same EVA, new interface. Your Mac runs the EVA server; your phone runs a PWA
that talks to her over HTTPS. Voice in, voice out, every tool your CLI EVA
has — including the local filesystem on the Mac.

```
   ┌──────────────────────┐         ┌──────────────────────┐
   │       Phone          │         │         Mac          │
   │  ┌────────────────┐  │  HTTPS  │  ┌────────────────┐  │
   │  │  EVA PWA       │◄─┼─────────┼─►│  jarvis-serve  │  │
   │  │  (Safari)      │  │  bearer │  │  FastAPI       │  │
   │  └────────────────┘  │   token │  └───────┬────────┘  │
   └──────────────────────┘         │          │           │
              ▲                     │  ┌───────▼────────┐  │
              │ Web Speech (STT/TTS)│  │  EVA agent     │  │
              ▼                     │  │  + tools       │  │
        Microphone + speaker        │  └────────────────┘  │
                                    └──────────────────────┘
```

This guide assumes the Cloudflare Tunnel + `/authorize`-gated security model.

---

## 1. Start the server on the Mac

```bash
cd jarvis
source .venv/bin/activate           # if you set one up
pip install -e .                    # picks up new deps: fastapi, uvicorn
jarvis-serve --cwd ~/projects       # workspace EVA operates in
```

On first start she generates and prints an auth token:

```
[EVA] Generated auth token. Pair your phone with this value:
[EVA]   abc123_long_random_token_xyz
[EVA] Stored at /Users/you/.jarvis/server_token (chmod 600).
```

Save that — your phone will need it.

To pin your own token instead: `export JARVIS_AUTH_TOKEN=...` before starting.

She listens on `127.0.0.1:8765` by default (localhost only — Cloudflare Tunnel
reaches her without needing to bind to `0.0.0.0`).

---

## 2. Expose her over Cloudflare Tunnel

You need:

- A Cloudflare account (free tier is fine).
- A domain on Cloudflare (any TLD they manage works).
- `cloudflared` installed on the Mac: `brew install cloudflared`.

### One-time setup

```bash
# Authenticate cloudflared with your Cloudflare account
cloudflared tunnel login

# Create a named tunnel
cloudflared tunnel create eva

# Note the tunnel UUID it prints. Then create a config file:
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml <<'YAML'
tunnel: <YOUR-TUNNEL-UUID>
credentials-file: /Users/you/.cloudflared/<YOUR-TUNNEL-UUID>.json

ingress:
  - hostname: eva.your-domain.com
    service: http://127.0.0.1:8765
  - service: http_status:404
YAML

# Route the hostname to the tunnel
cloudflared tunnel route dns eva eva.your-domain.com

# Run it (in a separate terminal / launchd / brew services)
cloudflared tunnel run eva
```

Now `https://eva.your-domain.com` proxies to EVA on the Mac. TLS is handled
by Cloudflare. The Mac never opens a port to the internet.

### Run it on boot

```bash
sudo cloudflared service install
```

This installs the tunnel as a launchd service so it survives reboots.

### Quick-and-dirty alternative

If you don't want a real domain, `cloudflared tunnel --url http://127.0.0.1:8765`
gives you a one-shot random `*.trycloudflare.com` URL that works for as long
as the command is running. Good for testing, bad for a permanent EVA.

---

## 3. Pair your phone

1. Open `https://eva.your-domain.com` in **Safari** on iPhone (Chrome on Android works too).
2. Paste the URL and the auth token. Hit **Establish connection**.
3. EVA says *"Connection established."* — you're in.

### Install as an app

- **iPhone**: tap Share → *Add to Home Screen*. EVA gets her own icon and
  launches fullscreen with no browser chrome.
- **Android**: Chrome shows an *Install app* prompt automatically, or use the
  menu → *Add to Home screen*.

The PWA is offline-capable for the shell (cached service worker) — though
without the server she can only show "offline".

---

## 4. Use her

- **Type**: usual chat input, Enter to send.
- **Talk**: tap the mic. Web Speech recognizes your speech, sends it.
- **Listen**: tap the speaker icon to toggle TTS. iOS Safari needs a user
  gesture before it'll synthesize the first time — toggling voice on counts.
- **Tools she has**: read files / list dirs / `git status` / search OSINT
  corpus / web search / web fetch / code execution / persistent memory /
  system info (battery, time, disk, network of the Mac).

### Voice on iOS

Web Speech API works on iOS Safari 14.5+ but has quirks:

- The first mic tap may show a permission prompt — accept once.
- If she stops speaking mid-sentence after a screen lock, that's iOS suspending
  the background tab. Reopen the PWA to resume.
- The picked voice depends on what's installed. EVA looks for "Ava" → "Allison"
  → "Samantha" → any en-US. Install extra voices via *Settings → Accessibility
  → Spoken Content → Voices → English*.

---

## 5. Destructive operations — the lock

By default the phone EVA can read everything but can't `rm`, `write_file`,
`sudo`, or anything else marked destructive. The lock icon in the top right
cycles:

| Icon | Mode | Effect |
| --- | --- | --- |
| 🔒 | `deny` (default) | All destructive ops fail. EVA reports "requires operator authorization." |
| 🔑 | `one_shot` | Next destructive op succeeds, then re-locks. |
| 🔓 | `session` | All destructive ops allowed for 10 minutes, then re-locks. |

You set it from the phone — EVA cannot self-authorize. Tap once for one-shot,
again for a session, again to lock.

The CLI EVA (running on the Mac directly) ignores this and uses interactive
confirm prompts as before — the gate is server-mode specific.

---

## 6. Server admin endpoints

For scripting / iOS Shortcuts / a Telegram bot you build later:

```
GET    /api/health                       no auth — liveness check
GET    /api/state                        bearer  — model, effort, auth mode, memory count
POST   /api/chat        {message}        bearer  — SSE stream of events
POST   /api/reset                        bearer  — clear conversation
POST   /api/authorize   {mode, ttl}      bearer  — set destructive-op gate
GET    /api/memory                       bearer  — list memory entries
DELETE /api/memory/{key}                 bearer  — delete one
```

SSE events (`event: event`):

```json
{ "kind": "text", "text": "Acknowledged. " }
{ "kind": "tool_use_start", "tool_name": "web_search" }
{ "kind": "error", "text": "[WARN] ...", "is_error": false }
{ "kind": "turn_end" }
```

There's also `event: state` (full state snapshot at turn boundaries) and
`event: done` (stream finished).

---

## 7. iOS Shortcuts integration (Hey Siri, ask EVA…)

If you want Siri to talk to EVA:

1. Shortcuts app → **New Shortcut**.
2. **Dictate Text** → captures your voice.
3. **Get Contents of URL** →
   - URL: `https://eva.your-domain.com/api/chat`
   - Method: POST
   - Headers: `Authorization: Bearer <your-token>`, `Content-Type: application/json`
   - Body (JSON): `{ "message": "<Dictated Text variable>" }`
4. **Get Text from Input** to pull the response body (the streaming text — Siri
   only sees the final chunk; for a real streaming Siri experience write a small
   server-side `/api/chat_blocking` endpoint that buffers and returns once).
5. **Speak Text** → reads the response aloud.
6. Name the shortcut "Ask EVA". Now *"Hey Siri, ask EVA"* works hands-free.

A blocking endpoint is trivial to add — see `jarvis/server.py` and adapt
the streaming handler to await the generator and return JSON.

---

## 8. Failure modes

| Symptom | Cause | Fix |
| --- | --- | --- |
| PWA loads but says "offline" | Server not running, or Cloudflare tunnel down | `jarvis-serve` and `cloudflared tunnel run eva` both need to be alive |
| `401 invalid token` | Wrong token, or it rotated | Tap menu → Unpair, re-enter |
| Mic button does nothing | Browser doesn't support Web Speech API, or permission denied | Use Safari (iOS) / Chrome (Android); reset site permissions |
| EVA refuses destructive command | Authorization locked | Tap 🔒 in topbar to switch to 🔑 (one-shot) or 🔓 (session) |
| TTS silent | iOS hasn't been gestured into speaking yet | Tap the speaker icon; she'll say "Voice channel open." |
| Stream cuts off after ~30s on Cloudflare | Free-plan idle timeout | Either don't worry about it (turn ends fast) or upgrade to Cloudflare's paid tier with longer SSE timeouts |
| Speech recognition stops after one sentence | Web Speech API is single-shot by default | Tap mic again. Continuous mode is supported but unreliable on iOS — single-shot is more dependable |
