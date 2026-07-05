import pandas as pd

# Passes
df = pd.read_csv('output/1953854_Mexico_vs_South_Korea/passes.csv')
print('=== PASSES SAMPLE (first 10) ===')
cols = ['minute','second','playerName','h_a','x','y','endX','endY','outcomeType','passLength','passDirection','passType']
print(df[cols].head(10).to_string())
print(f'\nTotal passes: {len(df)}')
print(f'Successful: {len(df[df.outcomeType=="Successful"])}')
print(f'Unsuccessful: {len(df[df.outcomeType=="Unsuccessful"])}')

# Shots
print('\n\n=== SHOTS ===')
shots = pd.read_csv('output/1953854_Mexico_vs_South_Korea/shots.csv')
cols2 = ['minute','playerName','h_a','x','y','isGoal','shotBodyType','situation','outcomeType']
print(shots[cols2].to_string())

# Player stats sample
print('\n\n=== PLAYER STATS (first 5 cols sample) ===')
ps = pd.read_csv('output/1953854_Mexico_vs_South_Korea/player_stats.csv')
print(ps[['playerName','team','position','isFirstEleven','shirtNo']].head(15).to_string())
print(f'\nTotal stat columns: {ps.shape[1]}')

# Events overview
print('\n\n=== EVENT TYPES ===')
ev = pd.read_csv('output/1953854_Mexico_vs_South_Korea/all_events.csv')
print(ev['type'].value_counts().to_string())
print(f'\nTotal events: {len(ev)}, Total columns: {ev.shape[1]}')
