# EVA

> *"Establishing connection. Standing by, Commander."*

A personal AI commander for your workstation. Persona modeled on EVA — the
Electronic Video Agent from *Command & Conquer: Red Alert*. Powered by Claude
Opus 4.7 with adaptive thinking, server-side web search, code execution, and a
local tool surface that gives EVA real reach into your machine.

This is the Iron-Man-Jarvis-in-spirit: live in your terminal, can run things,
remembers you, and speaks to you in EVA's voice when you want her to.

---

## What EVA can do

**Out of the box (v1):**

- Stream a response while you watch it land, in EVA's voice if voice mode is on
- Search the live web and fetch URLs (Anthropic's server-side `web_search` / `web_fetch`)
- Execute Python in a sandboxed code-execution container for math, parsing, charts
- Read and search files on your machine
- Write files and run shell commands — with an authorization prompt for anything destructive
- Report system telemetry (time, OS, hostname, network, disk, **macOS battery**)
- Persistent memory across sessions — EVA remembers your name, projects, preferences
- OSINT triage — given a target or technique, EVA searches the curated
  `Awesome-OSINT-For-Everything` corpus on this workstation for the right tool
- Text-to-speech via macOS `say` using the "Ava" voice (Red Alert cadence at 210 wpm)

Voice in: not in v1 for the CLI. On the phone, voice in is built-in via the
Web Speech API. Wire up Whisper for the CLI later — install with
`pip install '.[voice-stt]'` and the optional STT path is ready for an
implementation.

**EVA on your phone:** `jarvis-serve` starts an HTTPS-ready FastAPI server
that drives the same agent, plus a PWA frontend with voice in/out. Pair your
iPhone via Cloudflare Tunnel and EVA is reachable anywhere. See
[MOBILE.md](MOBILE.md) for the full deployment walkthrough.

---

## Install

Requires Python 3.10+. On macOS for voice, no extra install — `say` ships with the OS.

```bash
cd jarvis
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Set your API key:

```bash
cp .env.example .env
# Edit .env and add ANTHROPIC_API_KEY
```

Or just export it:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Run

```bash
# Start the REPL
jarvis

# Same thing
eva

# Start with voice on (macOS only)
jarvis --voice

# One-shot question
jarvis "what's my battery level and what time zone am I in?"

# Different model or effort level
jarvis --model claude-opus-4-7 --effort max
```

The first line says *"EVA online. Standing by, Commander."* if voice is enabled.

---

## Slash commands

| Command | Effect |
| --- | --- |
| `/help` | Show command list |
| `/voice` | Toggle TTS on/off |
| `/memory` | Dump EVA's persistent memory of you |
| `/forget KEY` | Delete a memory entry |
| `/reset` | Clear conversation buffer (keeps long-term memory) |
| `/cwd PATH` | Reassign EVA's working directory |
| `/model ID` | Switch Claude model mid-session |
| `/effort LEVEL` | low / medium / high / xhigh / max |
| `/quit` | Exit |

Ctrl-C interrupts EVA mid-response (the next line cancels her current utterance too). Ctrl-D quits.

---

## Safety

EVA gates anything destructive behind an operator confirmation prompt:

- `write_file` always asks before writing to disk
- `shell_exec` asks before running commands containing `rm`, `mv`, `dd`, `sudo`, `git push`,
  redirection (`>` / `>>`), package installs, etc. — and you can force the prompt
  with `confirm=true` in the tool call

Confirmations are interactive — EVA cannot self-approve.

Read-only operations (reading files, listing directories, `git status`, `ps`, web
search, code execution in the sandbox, memory recall) run without prompting.

---

## Configuration (env vars)

| Variable | Default | Effect |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | *(required)* | Your Anthropic API key |
| `JARVIS_MODEL` | `claude-opus-4-7` | Claude model ID |
| `JARVIS_EFFORT` | `xhigh` | Reasoning depth: low / medium / high / xhigh / max |
| `JARVIS_VOICE` | `Ava` | Any `say -v ?` voice. Try `Samantha`, `Karen`, `Allison`, `Victoria` |
| `JARVIS_SPEAK_RATE` | `210` | `say` words per minute |
| `JARVIS_SPEAK` | `0` | `1` to enable TTS at startup |
| `JARVIS_USER_NAME` | `Commander` | What EVA calls you |
| `JARVIS_HOME` | `~/.jarvis` | State directory (memory, history, logs) |

---

## Architecture

```
jarvis/
├── cli.py          # REPL, slash commands, Rich UI, voice flush during streaming
├── agent.py        # Anthropic streaming client + manual tool-use loop
├── persona.py      # EVA system prompt (cached via cache_control)
├── memory.py       # JSON-backed persistent memory store
├── voice.py        # macOS `say` TTS backend
├── config.py       # env / .env loader
└── tools/          # client-side tool surface
    ├── files.py    # read_file, write_file, list_dir, search_files
    ├── shell.py    # shell_exec with destructive-action gating
    ├── memory.py   # remember, recall, forget
    ├── system.py   # get_time, system_info, disk_usage, network_info
    ├── osint.py    # osint_search, osint_sections (uses repo's README)
    └── voice.py    # speak (ad-hoc TTS)
```

EVA also has these **server-side** tools provided by Anthropic — no install,
no API keys, no quota of yours to manage:

- `web_search` (`web_search_20260209`)
- `web_fetch` (`web_fetch_20260209`)
- `code_execution` (`code_execution_20260120`)

### How streaming + tool use is wired

`agent.py` uses the manual tool-use loop pattern from the Claude API guidance:
`client.messages.stream()` per turn, parse stream events for live UI updates,
collect the final message with `.get_final_message()`, dispatch any
`tool_use` blocks to the local tool registry, append `tool_result` blocks to
the message history, loop. Stops on `end_turn`, `refusal`, `max_tokens`, or
iteration cap.

### Prompt caching

The system prompt and the tool list are stable across a session — both carry
`cache_control: {type: "ephemeral"}`. The variable bit (the conversation
history) lives at the end of the message array where it doesn't invalidate
the cached prefix. EVA's per-turn cost stays low even after a long
conversation.

### Adaptive thinking + effort

Configured for Opus 4.7's best-in-class reasoning: `thinking: {type:
"adaptive"}` lets Claude decide when to think and how much, and
`output_config: {effort: "xhigh"}` makes that thinking deep enough for
agentic work without going to `max`. Override per-session via
`/effort max` if you want maximum intelligence.

---

## Extending EVA

Adding a new tool: drop a module in `jarvis/tools/`, export a `TOOLS: list[Tool]`
following the pattern in `tools/memory.py`, and import it in `tools/__init__.py`.
The registry, schema export, and dispatcher are wired automatically.

Adding a new voice backend: implement the `VoiceEngine` interface in
`jarvis/voice.py` — `speak(text, blocking)`, `stop()`, `available`, `enabled`.
ElevenLabs, Coqui, Piper, etc. all fit cleanly.

---

## License

MIT — same as the parent repository.
