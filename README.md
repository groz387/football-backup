# Scraping Whoscored Event Data
![alt text](https://github.com/Ali-Hasan-Khan/Scrape-Whoscored-Event-Data/blob/main/logo.jpg "Whoscored")

Tool to scrape match event data from [Whoscored](http://whoscored.com/ "Whoscored")'s chalkboard using **Selenium**. 

Installation:
1) `git clone https://github.com/Ali-Hasan-Khan/Scrape-Whoscored-Event-Data.git`

2) `pip install -r requirements.txt`

3) For some additional visual customisations replace **linecollection.py** with the one present in mplsoccer folder on your machine (somewhere here: ~\anaconda3\Lib\site-packages\mplsoccer). [Recommended for inverted gradient effect in pass maps] 
  
4) Follow **tutorial.ipynb** for guide.

## Audited Video Pipeline

This fork includes `video_pipeline.py`, an interactive match-analysis video builder that consumes the existing scraper exports in `output/<match>/`.

Quick visual-master render from an existing export:

```bash
python video_pipeline.py --match-dir output/1953861_Scotland_vs_Morocco --auto
```

`--auto` (and interactive mode) tries to fetch a **short public highlight of
that fixture** via yt-dlp and caches it under `output/<match>/clips/` so reruns
do not hit the network. Queries are built from the audit (teams, score,
competition, date, scorer minutes). Titles are ranked so press conferences,
full-match dumps, and the wrong fixture are skipped. A ~0.5s live-clip smash
sits between the hook claim and punch when a file lands; if search or download
fails the recap continues graphics-only.

```bash
python video_pipeline.py --match-dir output/1953861_Scotland_vs_Morocco --auto --no-fetch-clip
python video_pipeline.py --match-dir output/1953861_Scotland_vs_Morocco --auto --clip path/to/highlight.mp4
python video_pipeline.py --match-dir output/1953861_Scotland_vs_Morocco --auto --refetch-clip
```

By default this produces a silent, TikTok-style visual master and a short
human voiceover recording script. Attach a recorded human narration file with:

```bash
python video_pipeline.py --match-dir output/1953861_Scotland_vs_Morocco --auto --voiceover-file path/to/human_voiceover.wav
```

Windows SAPI text-to-speech is available only as a rough-draft fallback and must
be requested explicitly with `--sapi-tts`.

Interactive mode with approval checkpoints:

```bash
python video_pipeline.py --interactive
```

Outputs are written to `video_output/<match>/`:

- `data_audit.json` records verified metrics and blocked claims.
- `video_plan.json` records selected visualizations and scene durations.
- `SCRIPT.md`, `voiceover.txt`, `voiceover_recording_script.txt`, and `subtitles.srt` are generated for review/editing.
- `assets/*.png` contains vertical frames for the video.
- `match_video.mp4` is assembled with a supplied human voiceover, or silently when no voiceover file is provided.

Gemini is optional. Set `GEMINI_API_KEY` and, if needed, `GEMINI_MODEL` before running with `--use-gemini`. The pipeline still works without Gemini using deterministic data-grounded selection and script generation.

Important data rule: the engine will not invent xG or xGOT. If those fields are not present in the local WhoScored export or an enrichment provider, the xG/xGOT visualization is blocked in `data_audit.json`.



Reach me [here](https://twitter.com/rockingAli5) for any kind of help :) 

Special thanks to [Laurie Shaw](https://twitter.com/EightyFivePoint) for Expected Possession Value model ([check out his work here](http://eightyfivepoints.blogspot.com/)).

For any help/suggestion regarding mplsoccer reach out to the creators: [Andy](https://twitter.com/numberstorm), [Anmol](https://twitter.com/slothfulwave612).
