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
    culture   curse bookends (first + last sentence only) and Gemini register
    script_culture  tagged ElevenLabs v3 voiceover text + Gemini culture brief
    elevenlabs_tts  Liam Callahan / eleven_v3 TTS (approve / regenerate)
    ingest    Livescore URL parse + WhoScored health + stub fallbacks
    colors    club/national kits, Barça burgundy/gold, home/away clash swap
    resolve_match  typed Livescore fixture + adapter protocol (never invents x/y)
    livescore  studio probe: resolve_url → ingest.resolve
    scrape    WhoScored live / saved-HTML scrape (studio Scrape button)
    studio_api  thin HTTP helpers for the local studio console (no second brain)

Nothing in a lower layer imports from a higher one.
"""

__all__ = [
    "ab_hooks",
    "approvals",
    "audit",
    "audio",
    "batch",
    "cast",
    "clips",
    "colors",
    "config",
    "culture",
    "data",
    "director",
    "elevenlabs_tts",
    "draw",
    "export_pack",
    "farm",
    "graphs",
    "growth",
    "hooks",
    "i18n",
    "ingest",
    "livescore",
    "locale_meta",
    "logos",
    "longform",
    "music_beds",
    "platforms",
    "retention",
    "resolve_match",
    "safe_zones",
    "scrape",
    "scenes",
    "script_culture",
    "studio_api",
    "theme",
    "thumbnails",
    "timing",
    "video",
    "viral_audit",
    "voice",
]
