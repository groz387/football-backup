"""Match-recap video pipeline.

Layers, from the bottom up:

    theme     design tokens: palette, typography, team identity
    data      loading a scraped export into a MatchBundle
    audit     every number the video is allowed to say
    cast      1-2 star players, locked fact packs, search aliases
    director  which visuals to use and what the narration says
    timing    how long each scene is on screen
    draw      low-level drawing primitives and the layout grid
    scenes    one renderer per visualization
    video     frame rendering and mp4 assembly
    voice     narration audio
    audio     original music beds, SFX, ducking, loudnorm
    music_beds ffmpeg-lavfi loops (no catalog rips)
    platforms social export profiles (TikTok / Reels / Shorts / 16:9 / square)
    export_pack ffmpeg pack from one portrait master
    safe_zones  caption / hook placement for mute-first social chrome
    growth    bilingual posting pack (titles, hashtags, thumbs)
    thumbnails  huge overlay JPGs for that pack
    longform  YouTube 3–8 min pacing, chapters, no silent padding
    batch     language × format farm; optional recap.platforms / recap.growth
    ab_hooks  A/B picker for fact-locked hook variants

Nothing in a lower layer imports from a higher one.
"""

__all__ = [
    "ab_hooks",
    "audit",
    "audio",
    "batch",
    "cast",
    "clips",
    "data",
    "director",
    "draw",
    "export_pack",
    "graphs",
    "growth",
    "hooks",
    "i18n",
    "locale_meta",
    "logos",
    "longform",
    "music_beds",
    "platforms",
    "retention",
    "safe_zones",
    "scenes",
    "theme",
    "thumbnails",
    "timing",
    "video",
    "viral_audit",
    "voice",
]
