# Recap Studio operator guide

Run every command from the repository root (the folder containing
`video_pipeline.py`, `scrape_match.py`, and `studio/`).

Scrape-Backup (`Documents\Scrape-Backup`) is the operator's local archive.
This tree is the `football-backup` recap core plus the Studio dashboard.

## Windows setup

```bat
cd "C:\Users\Murad Baghirli\Desktop\Scrape-Whoscored-Event-Data"
git fetch origin
git checkout cursor/studio-rehaul-cf63
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
   match facts, scene order and protected names. `auto` uses Groq when
   configured, then Gemini. Offline localization is visibly marked partial.
7. Draft scripts. Review each card's word count and allowed numbers, then
   approve each language.
8. Click **Check ElevenLabs credits**, then generate/listen/approve each voice.
9. Produce with voiceover is enabled only when every selected script and voice is approved.
   **Render MP4s (no voice)** writes `video_output\<language>\<match>\match_video.mp4`
   after scripts are approved, even when ElevenLabs fails.

Silent MP4s use ffmpeg `settb`/`setpts` normalization and `apad`. There is no
silent stub VO pretending to be a success. Burned center-stroke captions stay
off unless you pass `--burn-captions`.

## Contextual translation

```dotenv
GEMINI_API_KEY=
GEMINI_SCRIPT_MODEL=gemini-2.5-pro

GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
TRANSLATION_PROVIDER=auto
```

Groq is the default whole-script translator (`openai/gpt-oss-120b`, with
`qwen/qwen3.8-27b` then `qwen/qwen3.6-27b` if that model is unavailable).
Gemini remains an optional fallback **and** the script writer when keyed.
Both have account quotas. Studio never labels either one “unlimited.” A
translation is accepted only when every scene returns and its digits, scorelines,
minutes and names pass the lock.

## ElevenLabs HTTP 402

402 is returned by ElevenLabs, not ffmpeg. A 402 is **not** automatically
“credits exhausted.” Studio now:

- shows the raw ElevenLabs status/message;
- retries `eleven_multilingual_v2` / `eleven_turbo_v2_5` when `eleven_v3` is blocked;
- appends the live remaining character count from `/v1/user/subscription`.

True account quota is only claimed when ElevenLabs says the monthly character
quota/credits are gone. Model-specific v3 quota is treated as a model fallback.

Configure `.env` (never commit it):

```dotenv
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_NAME=Liam Callahan - Witty Media Person
ELEVENLABS_MODEL=eleven_v3
ELEVENLABS_STYLE=robust
```

## Honest data policy

- WhoScored is primary for shot maps, heatmaps, pass networks and goal chains.
- Flashscore fallback provides only source-backed score, incidents and stats
  (including provider xG when Flashscore actually publishes it).
- x/y and xG are never fabricated.
- Tracking-only graphics remain unavailable when coordinates are absent or
  reconstructed.
- Swearing / cultural spice stays on the hook and the close. Analysis cards
  are evidence sentences tied to audited numbers.
