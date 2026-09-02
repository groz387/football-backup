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
    "clips",
    "data",
    "director",
    "draw",
    "graphs",
    "hooks",
    "i18n",
    "locale_meta",
    "logos",
    "scenes",
    "theme",
    "timing",
    "video",
    "viral_audit",
    "voice",
]
