import os
import re
import json
import asyncio
import argparse
from pathlib import Path

async def verify_match(whoscored_dir: str, fotmob_url: str):
    """
    Reads the WhoScored match_dossier.json and compares stats 
    against the live FotMob match page.
    """
    path = Path(whoscored_dir)
    dossier_path = path / "match_dossier.json"
    
    if not dossier_path.exists():
        print(f"Error: {dossier_path} not found. Run --summarize first.")
        return

    with open(dossier_path, "r", encoding="utf-8") as f:
        ws_data = json.load(f)

    # Extract FotMob match ID
    match = re.search(r'#(\d+)', fotmob_url)
    if not match:
        match = re.search(r'/matches/.*?/(.*?)[/#]', fotmob_url) # fallback for other formats
        
    fm_id = match.group(1) if match else None
    if not fm_id:
        print("Error: Could not extract FotMob Match ID from URL.")
        return

    print(f"\n[VERIFY] Launching nodriver to scrape FotMob Match ID {fm_id}...")
    
    try:
        import nodriver as uc
    except ImportError:
        print("nodriver not installed.")
        return

    browser = await uc.start(headless=False)
    api_url = f"https://www.fotmob.com/api/matchDetails?matchId={fm_id}"
    tab = await browser.get(api_url)
    await asyncio.sleep(8) # Wait for cloudflare/api to load
    
    source = await tab.get_content()
    browser.stop()

    # Extract JSON from the page source (nodriver wraps it in <pre> tags if it's pure json)
    json_str = source
    if "<pre" in source:
        m = re.search(r'<pre.*?>(.*?)</pre>', source, re.DOTALL)
        if m:
            json_str = m.group(1)
            
    # Sometimes it's just raw text, strip HTML tags if any
    json_str = re.sub(r'<[^>]+>', '', json_str)
    
    try:
        fm_data = json.loads(json_str)
    except Exception as e:
        print("Failed to parse FotMob API response.")
        return

    print("\n" + "="*50)
    print("  VERIFICATION REPORT (WhoScored vs FotMob)")
    print("="*50)

    try:
        # FotMob stats structure: fm_data['content']['stats']['Periods']['All']['stats'][0]['stats']
        # This can be fragile, so we search through all stats
        stats_blocks = fm_data.get('content', {}).get('stats', {}).get('Periods', {}).get('All', {}).get('stats', [])
        fm_stats = {}
        for block in stats_blocks:
            for stat in block.get('stats', []):
                title = stat.get('title')
                vals = stat.get('stats') # [home_val, away_val]
                if title and vals:
                    fm_stats[title] = vals
        
        home_team = list(ws_data["team_stats"].keys())[0]
        away_team = list(ws_data["team_stats"].keys())[1]
        
        # 1. Compare Possession
        ws_poss_h = ws_data["team_stats"][home_team]["possession_pct"]
        ws_poss_a = ws_data["team_stats"][away_team]["possession_pct"]
        
        if "Ball possession" in fm_stats:
            fm_poss_h = int(str(fm_stats["Ball possession"][0]).replace('%',''))
            fm_poss_a = int(str(fm_stats["Ball possession"][1]).replace('%',''))
            
            diff = abs(ws_poss_h - fm_poss_h)
            mark = "[PASS]" if diff <= 3 else "[WARN]"
            print(f"{mark} Possession: WS ({ws_poss_h} - {ws_poss_a}) | FM ({fm_poss_h} - {fm_poss_a})")
        else:
            print("[INFO] FotMob Possession not found.")

        # 2. Compare Total Passes
        ws_pass_h = ws_data["team_stats"][home_team]["total_passes"]
        ws_pass_a = ws_data["team_stats"][away_team]["total_passes"]
        if "Passes" in fm_stats:
            fm_pass_h = int(fm_stats["Passes"][0])
            fm_pass_a = int(fm_stats["Passes"][1])
            diff = abs(ws_pass_h - fm_pass_h)
            mark = "[PASS]" if diff <= 30 else "[WARN]"
            print(f"{mark} Passes:     WS ({ws_pass_h} - {ws_pass_a}) | FM ({fm_pass_h} - {fm_pass_a})")
            
        # 3. Compare Shots
        ws_shot_h = ws_data["team_stats"][home_team]["shots"]
        ws_shot_a = ws_data["team_stats"][away_team]["shots"]
        if "Total shots" in fm_stats:
            fm_shot_h = int(fm_stats["Total shots"][0])
            fm_shot_a = int(fm_stats["Total shots"][1])
            diff = abs(ws_shot_h - fm_shot_h)
            mark = "[PASS]" if diff <= 2 else "[WARN]"
            print(f"{mark} Shots:      WS ({ws_shot_h} - {ws_shot_a}) | FM ({fm_shot_h} - {fm_shot_a})")
            
        print("\nNote: Minor deviations (<5%) are expected as Opta (WhoScored) and FotMob use different event definitions for borderline actions.")
        print("="*50)
        
    except Exception as e:
        print(f"Error extracting FotMob stats: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify WhoScored stats against FotMob.")
    parser.add_argument("--dir", required=True, help="Path to WhoScored output directory.")
    parser.add_argument("--url", required=True, help="FotMob Match URL.")
    args = parser.parse_args()
    
    asyncio.run(verify_match(args.dir, args.url))
