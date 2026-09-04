# Recap Studio operator guide

Run every command from the repository root (the folder containing
`video_pipeline.py`, `scrape_match.py`, and `studio/`).

`Documents\Scrape-Backup` is the operator's local archive. This tree is the
`football-backup` recap core (`feature/recap-pipeline-i18n`) plus the Studio
dashboard. Voiceover is optional. The working product path is
**Render MP4s (no voice)** after scripts are approved.

## Exact CMD steps to an MP4

```bat
cd "C:\Users\Murad Baghirli\Desktop\Scrape-Whoscored-Event-Data"
git fetch origin
git checkout cursor/studio-ready-cf63
pip install -r requirements.txt
copy .env.example .env
notepad .env
python -m studio
```

Open <http://127.0.0.1:8765>. If that port is occupied:

```bat
python -m studio --port 8766
```

In the dashboard, in this order:

1. Paste a Livescore URL, WhoScored URL, Flashscore URL, or pick an existing export.
2. Click **Load match**. If the export is already under `output\`, graphics appear.
3. If missing, click **Find + scrape sources**. Livescore searches WhoScored first
   (visible CMD on Windows), then Flashscore when the chalkboard is missing or
   limited. A Livescore event id is never treated as a WhoScored id.
4. Pick exactly 3 or 4 **available** evidence graphics.
5. Keep **17 words / section** unless a shorter sentence is required.
6. Pick languages. Whole-script translation uses Groq when configured
   (`openai/gpt-oss-120b`, then `qwen/qwen3.8-27b` / `qwen/qwen3.6-27b`).
   Gemini is optional. Offline localization is marked partial.
7. Click **Draft scripts**. Review word count and allowed numbers on each card.
8. Click **Approve script** for every selected language.
9. Click **Render MP4s (no voice)**. Wait until the job is `done`.
10. Download `match_video.mp4` from the produce row, or open
    `video_output\<language>\<match>\match_video.mp4`.

Voice is optional after that: **Check ElevenLabs credits**, generate/listen,
approve each VO, then **Produce with voiceover**. A 402 is not automatically
“credits exhausted”. Empty/silent stub audio is never treated as success.

## Checks

```bat
python -m unittest tests.test_studio_core tests.test_context_translation tests.test_elevenlabs_errors tests.test_source_chain -v
```

## Contextual translation

```dotenv
GEMINI_API_KEY=
GEMINI_SCRIPT_MODEL=gemini-2.5-pro

GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
TRANSLATION_PROVIDER=auto
```

Groq is the default whole-script translator. Gemini remains an optional
fallback. Studio never labels either one “unlimited.” A translation is accepted
only when every scene returns and its digits, scorelines, minutes and names
pass the lock.

## ElevenLabs HTTP 402

402 is returned by ElevenLabs, not ffmpeg. A 402 is **not** automatically
“credits exhausted.” Studio now:

- shows the raw ElevenLabs status/message;
- retries `eleven_multilingual_v2` / `eleven_turbo_v2_5` when `eleven_v3` is blocked;
- appends the live remaining character count from `/v1/user/subscription`;
- rejects empty or silent audio bodies instead of approving a stub VO.

True account quota is only claimed when ElevenLabs says the monthly character
quota/credits are gone. Model-specific v3 quota is treated as a model fallback.

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
- Swearing / cultural spice stays on the hook and the close. Analysis cards
  are evidence sentences tied to audited numbers.
