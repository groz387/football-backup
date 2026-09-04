# Recap Studio operator guide

Run every command from the repository root (the folder containing
`video_pipeline.py`, `scrape_match.py`, and `studio/`).

## Windows setup

```bat
cd "C:\Users\Murad Baghirli\Desktop\Scrape-Whoscored-Event-Data"
git fetch origin
git checkout cursor/recap-rebuild-cf63
pip install -r requirements.txt
copy .env.example .env
notepad .env
python -m studio
```

Open <http://127.0.0.1:8765>. If that port is occupied:

```bat
python -m studio --port 8766
```

## One-match workflow

1. Paste a Livescore URL, WhoScored URL, or pick an existing export.
2. **Load match** checks `output/` without scraping.
3. If missing, **Find + scrape sources**:
   - searches WhoScored by both teams and date;
   - opens `scrape_match.py` in a visible Windows CMD;
   - accepts WhoScored only as “full” when the export has a real event stream
     and precise x/y;
   - otherwise searches and opens the Flashscore fallback;
   - never treats a Livescore event id as a WhoScored id.
4. Pick exactly three or four **available** evidence graphics.
5. Keep **17 words / section** unless the statistic needs a shorter sentence.
6. Pick languages. One contextual request translates the complete story with
   match facts, scene order and protected names. `auto` uses DeepSeek when
   configured, then Gemini. Offline localization is visibly marked partial.
7. Draft scripts. Review each card's word count and allowed numbers, then
   approve each language.
8. Click **Check ElevenLabs credits**, then generate/listen/approve each voice.
9. Produce is enabled only when every selected script and voice is approved.
   **Render silent preview** tests the complete visual pipeline after scripts
   are approved, even when ElevenLabs has no credits.

## Contextual translation

```dotenv
GEMINI_API_KEY=
GEMINI_SCRIPT_MODEL=gemini-2.5-pro

# Optional alternative:
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
TRANSLATION_PROVIDER=auto
```

DeepSeek and Gemini both have account quotas. Studio never labels either one
“unlimited.” A translation is accepted only when every scene returns and its
digits, scorelines, minutes and names pass the lock.

## ElevenLabs HTTP 402

402 is returned by ElevenLabs, not ffmpeg. The Studio now distinguishes:

- credits exhausted — top up/wait for reset/add another key;
- model access denied — retry the next configured model;
- invalid key;
- voice unavailable;
- unusual activity/rate limiting.

Configure `.env` (never commit it):

```dotenv
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_NAME=Liam Callahan - Witty Media Person
ELEVENLABS_MODEL=eleven_v3
ELEVENLABS_STYLE=robust
```

For key rotation:

```dotenv
ELEVENLABS_API_KEYS=key_one,key_two
ELEVENLABS_PROXIES=http://proxy-one:port,http://proxy-two:port
```

## Honest data policy

- WhoScored is primary for shot maps, heatmaps, pass networks and goal chains.
- Flashscore fallback provides only source-backed score, incidents and stats
  (including provider xG when Flashscore actually publishes it).
- x/y and xG are never fabricated.
- Tracking-only graphics remain unavailable when coordinates are absent or
  reconstructed.
