# Match recap videos

CLI that turns a WhoScored chalkboard export into a vertical analysis video:
data audit, section picker, Gemini script, then one or more language packages
(video + narration files). No web UI.

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `GEMINI_API_KEY`. Groq is optional for
faster non-English translation (`GROQ_API_KEY`).

Scrape a match, then build a video:

```bash
python scrape_match.py --url "https://www.whoscored.com/matches/1953854/live/..."
python video_pipeline.py
```

Or from a saved page-source HTML file when Cloudflare blocks the browser:

```bash
python scrape_match.py --file saved_page.html
```

## ASCII interface

`python video_pipeline.py` is interactive by default:

1. Pick a match from `output/`
2. Accept the audited numbers
3. Keep, change, or redo the visualization plan
4. Approve the English Gemini script (or ask for a rewrite)
5. Choose one language, or several (`en,az,es`) — each language gets its own
   video, `narration.txt`, `SCRIPT.md`, and `voiceover_recording_script.txt`

Semi-automatic multi-language from the command line:

```bash
python video_pipeline.py --match-dir output/1994148_Real_Sociedad_vs_Celta_Vigo --language en,az,es --auto
```

Packages land in `video_output/<lang>/<match>/` when you ask for more than
English, and in `video_output/<match>/` for a single English run.

Voiceover is off. The narration files are the deliverable for recording later.
Attach a take with `--voiceover-file path.wav` if you want it on the master.

## Other useful flags

```bash
python video_pipeline.py --still --auto          # one image per scene
python video_pipeline.py --no-gemini --auto      # audited script only
python video_pipeline.py --team club --auto      # circular crests
python video_pipeline.py --colors "#004170" "#95BFE5"
```

Flashscore HTML can be turned into the same export shape:

```bash
python scrape_flashscore.py --file saved_flashscore.html
```
