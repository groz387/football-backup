# Rewrite Video Pipeline: Universality, Animations & Premium Aesthetics

## Problem Analysis

I've deeply analyzed every frame the pipeline produces and the 2040 lines of code. Here are the **three core failures**:

---

### 🔴 Problem 1: Hardcoded Scotland vs Morocco Narrative — Not Universal

The code is riddled with match-specific text that will break or look absurd for any other match:

| Location | Hardcoded Text | Why It Breaks |
|---|---|---|
| [Title card L1373](file:///c:/Users/Murad%20Baghirli/Desktop/Scrape-Whoscored-Event-Data/video_pipeline.py#L1373) | `"MOROCCO BUILT THIS"` | What if Morocco lost? What if it's Brazil vs Germany? |
| [Title card L1354-1356](file:///c:/Users/Murad%20Baghirli/Desktop/Scrape-Whoscored-Event-Data/video_pipeline.py#L1354-L1356) | Giant "52.0 SECONDS" hero number | Only works if the best goal chain is 52 seconds. A 3-3 game shouldn't lead with one chain's duration |
| [Stats card L1406](file:///c:/Users/Murad%20Baghirli/Desktop/Scrape-Whoscored-Event-Data/video_pipeline.py#L1406) | `"MOROCCO LED THE KEY RECEIPTS."` | Hardcoded team name. Wrong if home team led |
| [Momentum L1580](file:///c:/Users/Murad%20Baghirli/Desktop/Scrape-Whoscored-Event-Data/video_pipeline.py#L1580) | `"PRESSURE SWUNG LATE"` | Assumes pressure swung late. What if it swung early? |
| [Storyboard L835-837](file:///c:/Users/Murad%20Baghirli/Desktop/Scrape-Whoscored-Event-Data/video_pipeline.py#L835-L837) | Narration about "Fifty-two seconds" and "Morocco" | Literal match-specific text in fallback storyboard |
| [Zone control L1525](file:///c:/Users/Murad%20Baghirli/Desktop/Scrape-Whoscored-Event-Data/video_pipeline.py#L1525) | `"SCOTLAND BLUE / MOROCCO RED"` | Hardcoded team-color mapping text |
| [Flags L1227-1261](file:///c:/Users/Murad%20Baghirli/Desktop/Scrape-Whoscored-Event-Data/video_pipeline.py#L1227-L1261) | Hardcoded Scotland/Morocco flag drawers | Only 2 teams have flags; everything else gets a generic rectangle |

### 🔴 Problem 2: Zero Animations — Static Slideshow

The current video is literally a slideshow of static PNGs concatenated with ffmpeg. Each scene is a single frozen image displayed for 2-4 seconds. There are:
- **No transitions** between scenes (hard cuts only)
- **No element animations** (numbers don't count up, bars don't grow, arrows don't draw)
- **No motion** whatsoever — it feels like a PowerPoint, not a video

The ffmpeg pipeline does `concat` with no filters for transitions. The moviepy path uses `concatenate_videoclips` with no effects.

### 🔴 Problem 3: Flat, Lifeless Aesthetics

Looking at the actual frames:
- **Title card**: A giant "52.0" number floating over a barely-visible pitch with no visual hierarchy. The flags are tiny crude rectangles
- **Stats card**: Three dark boxes with numbers and monospace labels. No visual weight, no bars/rings, feels like a terminal dump
- **Zone control**: Diagonal triangle splits are confusing and ugly. Hard to read dominance at a glance
- **Momentum**: Adequate but the blank bottom 25% of the frame is wasted space
- **Close card**: Dead simple text dump with the score. No visual closure

---

## Proposed Changes

### Phase 1: Make Everything Universal (Data-Driven Text)

#### [MODIFY] [video_pipeline.py](file:///c:/Users/Murad%20Baghirli/Desktop/Scrape-Whoscored-Event-Data/video_pipeline.py)

**Title Card Rewrite** — Replace the hardcoded "52.0 SECONDS / MOROCCO BUILT THIS" hero with a **dynamic headline engine**:
- For a 1-0 or 0-1 win: Lead with the winning team's name + the defining stat (goal chain if available)
- For a 2-1/3-2 etc: Lead with the score + "X goals. The data tells the story."
- For a draw: Lead with "LEVEL ON THE SCOREBOARD" + the dominant stat angle
- For a 0-0: Lead with "ZERO GOALS. BUT NOT ZERO CHANCES." + shot/chance stats
- The hero number becomes contextual: could be possession %, could be shot differential, could be chain duration — whatever is the most dramatic stat for *this specific match*

**Stats Card Rewrite** — Replace `"MOROCCO LED THE KEY RECEIPTS."` with dynamic text that determines which team led and what the narrative is:
- `f"{dominant_team} LED THE KEY RECEIPTS."` when one team clearly dominates
- `"THE NUMBERS WERE SPLIT."` for close matches
- Add more stats: shots on target, corners, possession bars

**Momentum Title** — Replace `"PRESSURE SWUNG LATE"` with dynamic text based on where the peak actually occurred:
- Minutes 0-25: `"PRESSURE PEAKED EARLY"`
- Minutes 25-65: `"THE MIDDLE THIRD DECIDED IT"`
- Minutes 65+: `"PRESSURE SWUNG LATE"`

**Zone Control Labels** — Replace `"SCOTLAND BLUE / MOROCCO RED"` with `f"{bundle.home.upper()} / {bundle.away.upper()}"` using actual team colors

**Storyboard Fallback** — Rewrite `build_storyboard()` so every narration line is generated from data, never hardcoded text about specific teams

**Remove Hardcoded Flags** — Replace `draw_scotland_flag` / `draw_morocco_flag` with a universal team crest/badge system using colored circles with initials (like modern apps)

**Expand Team Color Table** — Add 30+ common international/club teams, and make the fallback algorithm smarter (generate pleasing colors from team name hash)

---

### Phase 2: Add Real Animations via Frame-by-Frame Rendering

#### [MODIFY] [video_pipeline.py](file:///c:/Users/Murad%20Baghirli/Desktop/Scrape-Whoscored-Event-Data/video_pipeline.py)

Instead of rendering 1 PNG per scene, render **multiple frames per scene** with progressive reveals:

**Animation System Architecture:**
- Each renderer gains an `animate=True` parameter that makes it produce N frames (e.g. 24 frames/sec × duration)
- A new `render_animated_scene()` function calls the renderer at different `progress` values (0.0 → 1.0)
- ffmpeg concatenates the frame sequences instead of static images

**Specific Animations:**
1. **Title Card**: Score digits count up from 0. Team names fade in from sides. Hero stat number counts up
2. **Stats Card**: Bars grow from 0 to their final width. Numbers count up with easing. Rows stagger-animate (row 1 appears, then row 2, then row 3)
3. **Goal Chain**: Passes draw one by one along the path, like a pen tracing the build-up. Impact burst pulses at the goal
4. **Momentum**: The chart fills left-to-right as if the match is playing. Goal markers drop in
5. **Zone Control**: Zones fade in from low opacity to final state, sweeping from left to right across the pitch
6. **Close Card**: Score pulses in, stats appear one by one with slide-up animation

**Transitions Between Scenes:**
- Add a 0.3s crossfade between scenes using ffmpeg's `xfade` filter
- Or render transition frames (fade to black, fade from black)

---

### Phase 3: Premium Visual Overhaul

#### [MODIFY] [video_pipeline.py](file:///c:/Users/Murad%20Baghirli/Desktop/Scrape-Whoscored-Event-Data/video_pipeline.py)

**Typography:**
- Replace `DejaVu Sans` with downloadable Google Fonts: **Inter** for body, **Space Grotesk** or **Bebas Neue** for display/headers, **JetBrains Mono** for mono
- Add font download helper that pulls from Google Fonts API on first run

**Color System Upgrade:**
- Add gradient backgrounds instead of flat `#0a0b08` — subtle radial gradient from center
- Add glow effects around key numbers (using matplotlib's blur/shadow)
- Implement a proper glass-panel effect for stat cards (semi-transparent with subtle border)

**Title Card Redesign:**
- Full-bleed background with team color gradient (home color → away color, subtle)
- Team badges as large colored circles with 3-letter abbreviations (like ESPN/Sky Sports)
- Score in premium typography with subtle drop shadow
- League/competition watermark (e.g., "FIFA WORLD CUP 2026 • GROUP C")

**Stats Card Redesign:**
- Horizontal comparison bars (like FotMob/Sofascore) instead of just numbers
- Each stat gets a full-width bar showing home vs away proportion
- Color-coded bars with rounded ends
- Add more metrics: Shots on Target, Corners, Fouls, Saves

**Zone Control Redesign:**
- Replace ugly diagonal triangle splits with a proper heatmap gradient
- Each cell shows a single blended color: pure home color when 100% home, pure away color when 100% away, blend in between
- Add touch count labels on all cells, not just top 4
- Subtle grid lines instead of harsh borders

**Momentum Redesign:**
- Fill the entire vertical space better
- Add team logos/abbreviations on the y-axis
- Smoother curve using cubic interpolation instead of step function
- Gradient fill under the curves

**Close Card Redesign:**
- Add team color accent bars
- Better visual hierarchy with the score as centerpiece
- Mini-stat icons next to each receipt line

---

## Open Questions

> [!IMPORTANT]
> **Font Installation**: Google Fonts like Inter/Bebas Neue need to be downloaded and registered with matplotlib. Should I bundle them in a `fonts/` directory in the project, or download them at runtime?

> [!IMPORTANT]
> **Animation Performance**: Rendering 24fps × ~18 seconds = ~432 frames per video. Each frame is a matplotlib figure render. This will take 2-5 minutes to render a single video. Is that acceptable, or should I target a lower framerate like 12fps for faster iteration?

> [!IMPORTANT]  
> **How many teams to support in the color table?** I can add the 32 World Cup 2026 teams, or expand to include top European clubs too. The fallback (auto-generated colors from team name) will work for any team regardless.

## Verification Plan

### Automated Tests
- Run the pipeline on the existing Scotland vs Morocco data and verify the output video exists and has proper duration
- Run with `--skip-video` to quickly verify all PNGs render without errors

### Manual Verification
- Visually compare before/after screenshots of each scene type
- Test with a hypothetical 3-3 draw to confirm universality (can mock data)
- Verify animations play smoothly in the output MP4
