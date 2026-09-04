"""Match-recap video pipeline.

Layers, from the bottom up:

    theme     design tokens: palette, typography, team identity
    data      loading a scraped export into a MatchBundle
    audit     every number the video is allowed to say
    director  which visuals to use and what the narration says
    timing    how long each scene is on screen
    draw      low-level drawing primitives and the layout grid
    scenes    one renderer per visualization
    video     frame rendering and mp4 assembly
    voice     narration audio

Nothing in a lower layer imports from a higher one.
"""

__all__ = [
    "audit",
    "audio",
    "approvals",
    "clips",
    "colors",
    "config",
    "data",
    "director",
    "draw",
    "elevenlabs_tts",
    "flashscore",
    "graphs",
    "hooks",
    "i18n",
    "logos",
    "ingest",
    "livescore",
    "resolve_match",
    "scrape",
    "scenes",
    "source_chain",
    "studio_api",
    "theme",
    "timing",
    "translation",
    "video",
    "viral_audit",
    "voice",
]
