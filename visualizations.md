The Visualization: A clean, minimal pitch asset plotting only the string of coordinates leading to a shocking goal (from goal_networks_data). Use directional arrows for passes, a glowing line for the assist, and a heavy burst metric at the point of the shot.

The Shock Factor / Hook: Perfect for the first 2 seconds of a short. "14 passes, 80 meters covered, completely bypassing the midfield in exactly 11 seconds. Here is how Spain unpicked the lock."
----

Chalkboard Dividers)
The Visualization: Divide the pitch into 5 horizontal zones or 18 tactical grids. Color-code the grids dynamically based on Touch Volume per team during specific 15-minute intervals.

The Shock Factor / Hook: Captures the momentum of an upset. "Look at the final 15 minutes: Team A was completely pinned inside their own final third, maintaining 0% presence in the opposition half, yet managed to score on their only breakaway."

----
xG vs. xGOT "Robbery" IndicatorThe Visualization: A dual-gauge metric or a 1x1 scatter plot representing a specific shot. Compare Expected Goals ($xG$ - the quality of the chance) against Expected Goals on Target ($xGOT$ - the quality of the actual finish/trajectory into the net).The Shock Factor / Hook: Instantly quantifies world-class goalkeeping or terrible finishing. "This shot had an xG of 0.03—a complete prayer—but the xGOT was 0.98, flying dead into the top corner. Total goalkeeper robbery."

----

The "Brick Wall" (Goalkeeper Masterclass):The Data: Compare Expected Goals on Target ($xGOT$) against actual goals conceded. $xGOT$ measures the quality of the finish, factoring in the exact shot trajectory.The Visualization: A 3D render or 2D glowing barrier over the goal frame, plotting the placement of every shot saved by the keeper, sized by the shot's $xGOT$ value.The Hook: "Spain generated enough shot quality to win comfortably, but the Cape Verde goalkeeper faced an $xGOT$ of 2.8 and saved absolutely everything. The ultimate brick wall."
----

The "Momentum Pendulum" (Tale of Two Halves):

The Data: Calculate Expected Threat (xT) or Field Tilt on a rolling 5-minute average to measure which team is actively controlling the most dangerous areas of the pitch.

The Visualization: A high-contrast, dual-colored wave graph filling the screen, showing the exact minute the momentum violently swung (e.g., after a substitution or tactical tweak).

The Hook: "Look at this momentum swing. Iran had 80% of the attacking threat in the first 45 minutes, but after halftime, New Zealand completely suffocated them."

----

The "Sterile Domination" (Tactical Stalemate):

The Data: Passing volume segmented by pitch thirds, paired with final-third entry success rates.

The Visualization: A pass network where the nodes in the defensive half are massive, but the links into the opposition's penalty area are completely severed or non-existent.

The Hook: "70% possession, but completely useless. Look at this passing network—thousands of passes at the back, but an absolute black hole in the final third."

----



Additional - Ananalysis of the overall heatmap, the standart stats(shots, possession, saves, fouls, corners all of that), analysis of FIFA ranking. 



I came up with different options for data visualization we can use, aside from default hetamaps and normal data. 
Here is what we will do on the analysis part of this project - script requests all the data necessary from our libarries/apis, multiple - https://soccerdataapi.com/, https://v3.football.api-sports.io , sportmonks.com, https://info.soccerfootball.info. To get all the necessary data for the visualization. We will decide on WHAT visualization from the set to use using an llm, by requesting the series of events and fifa ranking and match summary of a match and submitting it to the llm for it to decide with which three to go. ASide from 3 visualizations to do, the video will feature for every match the verbal analysis of the basic data - Ananalysis of the overall heatmap, the standart stats(shots, possession, saves, fouls, corners all of that), analysis of FIFA ranking. Also through submitting that to the llm with the data. Keep up with the original idea, analyze all APIS, tell me what to do which keys to get and how are we gonna build it. Build the script and lets see how it works, with generating 1 mock video on the latest world cup match. 



ANALYSE ALL THESE APIS DOCUMENTATIONS AND BUILD



First analyze the codebase and unserstand what going on in this project. Brief: "--BRIEF START-- This project scrapes the deepest level of football match data available from WhoScored.com. It doesn’t just grab the final score—it grabs every single event (every pass, shot, tackle, and foul) along with exact (x, y) pitch coordinates.
We then built a custom pipeline to automatically process this massive mathematical dataset into a lightweight tactical summary so you can feed it to an LLM (like ChatGPT or Llama) to auto-generate highly analytical YouTube/TikTok video scripts. --BRIEF END--"
Then I want to build the vizualization engine that HIGHLY UTILIZZES and properly, and I mean it should be pitch perfect working with data to make vizualization and interpret data without any hallucinations. I briefed some ideas we can use them but you can come up with some too. The idea here is to build a pipeline around dthis data extractor. I give a match, it gives out a video with narrated autdio, subtitieles, edit. Graphsa and charts beautifully edited and talked about, high reasoning and very good script talking about the given match, WHY the score is like that, what is the sensation, why did Home team loose or why did a less powerful team win etc. Gemini API for script writing, automated editing, step by step control in CLI with OKs and rejects and redo and change options. What I mean is the pipeline should have an interface in CLI where I start it, choose a match, and then each stage - data, script, chosen vizualizations, etc are OKed with me ad I have an option to ok, change or reject. After all that, we need to build an entire pipeline focused on HIGH QUALITY VIDEOS and Accurate data and data interpretations. 
