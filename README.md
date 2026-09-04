# Recap Studio

Local dashboard that automates recap video production in batch.

**Scrape-Backup was not on this cloud VM.** Visual + script foundation is
`feature/recap-pipeline-i18n` (the football-backup recap/draw/director/scenes
core). Studio (`studio/`) is the product UI.

```bash
python -m studio
```

Open `http://127.0.0.1:8765`. See [`STUDIO_GUIDE.md`](STUDIO_GUIDE.md).

## Produce path

1. Paste a Livescore / WhoScored URL or pick an export under `output/`.
2. Load match. If missing, **Find + scrape sources** (WhoScored first, Flashscore fallback).
3. Pick 3–4 available evidence graphics (backup pitch/time/territory cards + crisp touch mosaic).
4. Draft scripts (~17 words per analysis section). Approve each language.
5. **Render MP4s (no voice)** writes `video_output/<language>/<match>/match_video.mp4`.
6. Optional: ElevenLabs VO, then **Produce with voiceover**.

Keys live only in gitignored `.env` (`GROQ_API_KEY`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`).

## CLI

```bash
python video_pipeline.py --match-dir output/1953854_Mexico_vs_South_Korea --auto --skip-audio
```

Gemini is optional (`GEMINI_API_KEY`). Groq is the whole-script translator.
Do not invent xG or coordinates; blocked claims are recorded in `data_audit.json`.
