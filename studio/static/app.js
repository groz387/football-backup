const $ = (id) => document.getElementById(id);

const state = {
  settings: {},
  languages: [],
  matches: [],
  capabilities: {},
  job: null,
  lang: null,
  poll: null,
  scrapePoll: null,
  visualizations: [],
};

async function api(path, opts) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts && opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = data.detail || data.message || res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function selectedLangs() {
  return [...document.querySelectorAll(".lang input:checked")].map((el) => el.value);
}

function selectedViz() {
  return [...document.querySelectorAll(".viz input:checked")].map((el) => el.value);
}

function formSettings() {
  const colors = [$("colorHome").value.trim(), $("colorAway").value.trim()].filter(Boolean);
  return {
    url: $("url").value.trim(),
    match_dir: $("matchDir").value,
    languages: selectedLangs(),
    selected_visualizations: selectedViz(),
    visualization_count: Number($("visualizationCount")?.value || 4),
    words_per_section: Number($("wordsPerSection")?.value || 17),
    target_seconds: Number($("targetSeconds")?.value || 34),
    fps: Number($("fps")?.value || 30),
    translation_provider: $("translationProvider")?.value || "auto",
    require_context_translation: Boolean($("requireTranslation")?.checked),
    scrape_url: ($("scrapeUrl") && $("scrapeUrl").value.trim()) || "",
    html_path: ($("htmlPath") && $("htmlPath").value.trim()) || "",
    scrape_wait: Number(($("scrapeWait") && $("scrapeWait").value) || 15),
    hook_claim: $("hookClaim").value.trim(),
    hook_punch: $("hookPunch").value.trim(),
    bait_text: $("bait").value.trim(),
    team: $("team").value,
    colors,
    format: $("format").value,
    spoiler: $("spoiler").value,
    eleven_style: ($("elevenStyle") && $("elevenStyle").value) || "robust",
    kids: Boolean($("kids") && $("kids").checked),
    use_gemini: Boolean($("useGemini") && $("useGemini").checked),
    gemini_model: ($("geminiModel") && $("geminiModel").value.trim()) || "",
    star: ($("star") && $("star").value.trim()) || "auto",
    platforms: ($("platforms") && $("platforms").value.trim()) || "tiktok,reels,shorts",
    series_id: ($("seriesId") && $("seriesId").value.trim()) || "",
    voice_id: ($("elevenVoice") && $("elevenVoice").value.trim()) || "",
    eleven_model: ($("elevenModel") && $("elevenModel").value.trim()) || "eleven_v3",
    instruction: ($("instruction") && $("instruction").value.trim()) || "",
  };
}

function paintCaps(caps) {
  const bits = [
    ["pipeline", true],
    ["elevenlabs", caps.elevenlabs_configured || (caps.elevenlabs && !caps.stubbed?.elevenlabs_tts)],
    ["scrape", caps.scrape],
    ["gemini", caps.gemini_key],
    ["deepseek", caps.deepseek_key],
  ];
  $("caps").innerHTML = bits.map(([name, live]) =>
    `<span class="cap ${live ? "live" : "stub"}">${name} ${live ? "live" : "stub"}</span>`
  ).join("");
}

function paintMatches(matches, selected) {
  const sel = $("matchDir");
  const opts = ['<option value="">— pick an export —</option>']
    .concat(matches.map((m) =>
      `<option value="${m.match_dir}" ${m.match_dir === selected ? "selected" : ""}>${m.label} · ${m.name}</option>`
    ));
  sel.innerHTML = opts.join("");
}

function paintLangs(languages, chosen) {
  const set = new Set(chosen || []);
  $("langs").innerHTML = languages.map((lang) => `
    <label class="lang ${set.has(lang.code) ? "on" : ""}">
      <input type="checkbox" value="${lang.code}" ${set.has(lang.code) ? "checked" : ""} />
      <span>${lang.native}</span>
      <small>${lang.code}</small>
    </label>
  `).join("");
  $("langs").querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", () => {
      input.closest(".lang").classList.toggle("on", input.checked);
      persist();
    });
  });
}

function paintVisualizations(payload) {
  state.visualizations = payload?.options || [];
  const selected = new Set(payload?.selected || state.settings.selected_visualizations || []);
  $("vizOptions").innerHTML = state.visualizations.map((viz) => `
    <label class="viz ${viz.available ? "" : "off"}">
      <input type="checkbox" value="${escapeAttr(viz.id)}"
        ${selected.has(viz.id) ? "checked" : ""} ${viz.available ? "" : "disabled"} />
      <b>${escapeHtml(viz.title || viz.id)}</b>
      <span>${Number(viz.score || 0).toFixed(1)}</span>
      <small>${escapeHtml(viz.reason || "")}</small>
    </label>
  `).join("");
  $("vizOptions").querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", () => {
      const limit = Number($("visualizationCount").value || 4);
      const chosen = selectedViz();
      if (chosen.length > limit) {
        input.checked = false;
        $("resolveHint").textContent = `Pick exactly ${limit} graphics. Uncheck one before adding another.`;
      }
      persist();
    });
  });
}

async function loadVisualizations(matchDir) {
  if (!matchDir) return;
  const payload = await api("/api/visualizations", {
    method: "POST",
    body: { match_dir: matchDir, count: Number($("visualizationCount").value || 4) },
  });
  paintVisualizations(payload);
}

function applyColors(preview) {
  if (!preview) return;
  const home = preview.home || {};
  const away = preview.away || {};
  document.documentElement.style.setProperty("--home", home.primary || home.fill || "#a50044");
  document.documentElement.style.setProperty("--away", away.primary || away.fill || "#004d98");
  $("homeName").textContent = home.name || "Home";
  $("awayName").textContent = away.name || "Away";
  $("homeAbbr").textContent = home.abbr || "HOM";
  $("awayAbbr").textContent = away.abbr || "AWY";
  $("homeHex").textContent = home.primary || "auto";
  $("awayHex").textContent = away.primary || "auto";
  $("sideHome").style.background = home.primary || home.fill;
  $("sideAway").style.background = away.primary || away.fill;
}

function applyMatch(match) {
  if (!match) return;
  $("matchLabel").textContent = match.label || match.name;
  $("matchDir").value = match.match_dir;
}

async function persist() {
  const payload = formSettings();
  state.settings = await api("/api/settings", { method: "POST", body: payload });
}

function collectScenes() {
  return [...document.querySelectorAll(".scene")].map((node) => ({
    id: node.dataset.id,
    title: node.querySelector(".title").value,
    narration: node.querySelector(".narration").value,
    insight: node.querySelector(".insight").value,
  }));
}

function paintReview() {
  const job = state.job;
  if (!job) {
    $("reviewEmpty").hidden = false;
    $("reviewBody").hidden = true;
    return;
  }
  $("reviewEmpty").hidden = true;
  $("reviewBody").hidden = false;
  const langs = job.languages || Object.keys(job.packs || {});
  if (!state.lang || !langs.includes(state.lang)) state.lang = langs[0];
  $("langTabs").innerHTML = langs.map((code) =>
    `<button type="button" class="tab ${code === state.lang ? "on" : ""}" data-lang="${code}">${code}</button>`
  ).join("");
  $("langTabs").querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => { state.lang = btn.dataset.lang; paintReview(); });
  });
  const pack = job.packs[state.lang];
  $("scriptPill").textContent = `script ${pack.script_status}`;
  $("scriptPill").className = `pill ${
    pack.script_status === "approved" ? "ok"
      : pack.script_status === "translation_blocked" ? "warn" : ""
  }`;
  $("voicePill").textContent = `voice ${pack.voice_status}${pack.voice_stub ? " (stub)" : ""}`;
  $("voicePill").className = `pill ${pack.voice_status === "approved" ? "ok" : pack.voice_stub ? "warn" : ""}`;
  if ($("growthPill")) {
    const growthOn = Boolean(pack.growth || pack.growth_ready);
    $("growthPill").textContent = growthOn ? "growth ready" : "growth —";
    $("growthPill").className = `pill ${growthOn ? "ok" : ""}`;
  }
  if ($("bookendReview")) {
    $("bookendReview").textContent = `HOOK: ${pack.hook_claim || "—"}   ·   BAIT: ${pack.bait || "—"}`;
  }
  if ($("translationReview")) {
    const copy = pack.operator_copy || {};
    const source = copy.source_language || "director";
    const methods = [pack.translation_provider || copy.provider || "source"];
    const warning = [
      ...(pack.translation_warnings || []),
      ...(pack.script_warnings || []),
    ].join(" | ");
    $("translationReview").textContent =
      `Whole script: ${source} → ${pack.language}; ${methods.join(", ")}.${warning ? " REVIEW: " + warning : ""}`;
    $("translationReview").classList.toggle("error", Boolean(warning));
  }
  $("scenes").innerHTML = (pack.scenes || []).map((scene) => `
    <article class="scene" data-id="${scene.id}">
      <header><span>${scene.visualization}</span><span>${scene.hook ? "hook" : `${scene.word_count || 0} words`}</span></header>
      <input class="title" value="${escapeAttr(scene.title || "")}" />
      <textarea class="narration">${escapeHtml(scene.narration || "")}</textarea>
      <input class="insight" value="${escapeAttr(scene.insight || scene.comment_bait || "")}" placeholder="insight / bait" />
      <p class="evidence-note">Allowed evidence: ${(scene.fact_numbers || []).map(escapeHtml).join(", ") || "names / source events only"}</p>
    </article>
  `).join("");
  const player = $("player");
  if (pack.voice_path) {
    player.src = `/api/jobs/${job.id}/audio/${state.lang}?t=${Date.now()}`;
  } else {
    player.removeAttribute("src");
  }
  const preflight = job.voice_preflight || {};
  $("voiceNote").textContent = pack.voice_note
    || preflight.message
    || (pack.voice_stub ? "ElevenLabs unavailable — no audio was approved." : "");
  $("voiceNote").classList.toggle("error", pack.voice_status === "failed" || preflight.enough === false);
  paintProduce(job);
}

function paintProduce(job) {
  const prod = (job && job.production) || { status: "idle", percent: 0, log: [], stage: "idle" };
  const packs = (job && job.packs) || {};
  const blockers = [];
  const scriptBlockers = [];
  Object.entries(packs).forEach(([code, pack]) => {
    if (pack.script_status !== "approved") {
      blockers.push(`${code} script`);
      scriptBlockers.push(`${code} script`);
    }
    if (pack.voice_status !== "approved") blockers.push(`${code} voice`);
  });
  if ($("btnProduce")) {
    $("btnProduce").disabled = blockers.length > 0 || prod.status === "running";
    $("btnProduce").title = blockers.length
      ? `Approve before production: ${blockers.join(", ")}`
      : "Render all approved language packages";
  }
  if ($("btnPreviewVideo")) {
    $("btnPreviewVideo").disabled = scriptBlockers.length > 0 || prod.status === "running";
    $("btnPreviewVideo").title = scriptBlockers.length
      ? `Approve before preview: ${scriptBlockers.join(", ")}`
      : "Render approved scripts without voiceover";
  }
  $("barFill").style.width = `${prod.percent || 0}%`;
  $("prodStage").textContent = `${prod.status || "idle"} · ${prod.stage || ""} ${prod.error ? "· " + prod.error : ""}`;
  $("prodLog").textContent = (prod.log || []).slice(-40).join("\n");
  $("prodResults").innerHTML = (prod.results || []).map((row) =>
    `<p class="hint">${row.language}/${row.format} · ${row.status} · ${row.out_dir}${row.video ? " · " + row.video : ""}</p>`
  ).join("");
  if (prod.status === "running" && !state.poll) {
    state.poll = setInterval(async () => {
      state.job = await api(`/api/jobs/${job.id}`);
      paintReview();
      if (state.job.production.status !== "running") {
        clearInterval(state.poll);
        state.poll = null;
      }
    }, 1200);
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}
function escapeAttr(value) { return escapeHtml(value); }

function showScrapePanel(show, data) {
  const panel = $("scrapePanel");
  if (!panel) return;
  panel.hidden = !show;
  if (!show) return;
  if (data && data.scrape_kind === "livescore" && $("scrapeUrl")) {
    // A Livescore event id is never a WhoScored id. Keep the original URL so
    // the source chain searches by fixture rather than using a stale override.
    $("scrapeUrl").value = "";
  }
  if (data && data.scrape_url && $("scrapeUrl") && !$("scrapeUrl").value) {
    $("scrapeUrl").value = data.scrape_url;
  }
  if ($("scrapeHint")) {
    $("scrapeHint").textContent = (data && (data.scrape_hint || data.stub))
      || "No local export. Scrape WhoScored or import a saved page-source HTML.";
  }
}

function paintScrape(job) {
  if (!job) return;
  showScrapePanel(true, job);
  if ($("scrapeBar")) $("scrapeBar").style.width = `${job.percent || 0}%`;
  if ($("scrapeStage")) {
    $("scrapeStage").textContent = `${job.status || ""} · ${job.stage || ""} ${job.error ? "· " + job.error : ""}`;
  }
  if ($("scrapeLog")) {
    $("scrapeLog").hidden = !(job.log && job.log.length);
    $("scrapeLog").textContent = (job.log || []).slice(-30).join("\n");
  }
  if ($("sourceSteps")) {
    $("sourceSteps").innerHTML = (job.steps || []).map((step) =>
      `<p class="hint"><b>${escapeHtml(step.name || "step")}</b> — ${escapeHtml(step.status || "")}: ${escapeHtml(step.detail || "")}</p>`
    ).join("");
  }
}

async function refreshMatches(selected) {
  const data = await api("/api/matches");
  state.matches = data.matches || [];
  paintMatches(state.matches, selected || $("matchDir").value);
}

async function loadMatch() {
  $("resolveHint").textContent = "Resolving…";
  try {
    const data = await api("/api/resolve", { method: "POST", body: formSettings() });
    if (!data.ok) {
      $("resolveHint").textContent = data.stub || "Could not resolve that source.";
      showScrapePanel(Boolean(data.needs_scrape || data.can_scrape), data);
      return;
    }
    showScrapePanel(false);
    applyMatch(data.match);
    applyColors(data.colors);
    await loadVisualizations(data.match.match_dir);
    $("resolveHint").textContent = data.match.label;
    await persist();
  } catch (err) {
    $("resolveHint").textContent = err.message;
    showScrapePanel(true);
  }
}

async function scrapeMatch() {
  const s = formSettings();
  const url = s.scrape_url || s.url;
  const htmlPath = s.html_path;
  const file = $("htmlFile") && $("htmlFile").files && $("htmlFile").files[0];
  $("resolveHint").textContent = "Starting scrape…";
  showScrapePanel(true, { scrape_url: url, scrape_hint: "Scraping WhoScored…" });
  try {
    let job;
    if (file) {
      const body = new FormData();
      body.append("html_file", file);
      body.append("url", url || "");
      body.append("wait", String(s.scrape_wait || 15));
      const res = await fetch("/api/scrape/html", { method: "POST", body });
      job = await res.json();
      if (!res.ok) throw new Error(job.detail || job.message || res.statusText);
    } else {
      job = await api("/api/scrape", {
        method: "POST",
        body: { url, html_path: htmlPath, wait: s.scrape_wait },
      });
    }
    paintScrape(job);
    state.scrapePoll = setInterval(async () => {
      const next = await api(`/api/scrape/${job.id}`);
      paintScrape(next);
      if (next.status === "done") {
        clearInterval(state.scrapePoll);
        state.scrapePoll = null;
        await refreshMatches(next.match_dir);
        if (next.match) {
          applyMatch(next.match);
          applyColors(next.colors);
          await loadVisualizations(next.match.match_dir);
          $("resolveHint").textContent = `Scraped ${next.match.label}`;
        }
      } else if (next.status === "failed") {
        clearInterval(state.scrapePoll);
        state.scrapePoll = null;
        $("resolveHint").textContent = next.error || "Scrape failed.";
      }
    }, 1200);
  } catch (err) {
    $("resolveHint").textContent = err.message;
    showScrapePanel(true);
  }
}

async function previewColors() {
  const s = formSettings();
  if (!s.match_dir) return;
  try {
    const preview = await api("/api/preview-colors", {
      method: "POST",
      body: { match_dir: s.match_dir, team: s.team, colors: s.colors },
    });
    applyColors(preview);
  } catch (err) {
    $("resolveHint").textContent = err.message;
  }
}

async function draft() {
  $("resolveHint").textContent = "Drafting scripts…";
  try {
    const required = Number($("visualizationCount").value || 4);
    if (selectedViz().length !== required) {
      throw new Error(`Pick exactly ${required} available evidence graphics.`);
    }
    await persist();
    state.job = await api("/api/draft", { method: "POST", body: formSettings() });
    state.lang = (state.job.languages || [])[0];
    applyColors(state.job.colors);
    applyMatch(state.job.match);
    paintReview();
    $("resolveHint").textContent = `Drafted ${state.job.languages.join(", ")}`;
  } catch (err) {
    $("resolveHint").textContent = err.message;
  }
}

async function saveEdits() {
  if (!state.job) return;
  state.job = await api(`/api/jobs/${state.job.id}/scripts/${state.lang}`, {
    method: "POST",
    body: { action: "edit", scenes: collectScenes() },
  });
  paintReview();
}

async function approveScript() {
  if (!state.job) return;
  state.job = await api(`/api/jobs/${state.job.id}/scripts/${state.lang}`, {
    method: "POST",
    body: { action: "approve", scenes: collectScenes() },
  });
  paintReview();
}

async function regenVoice() {
  if (!state.job) return;
  $("voiceNote").textContent = "Generating…";
  state.job = await api(`/api/jobs/${state.job.id}/voice/${state.lang}`, {
    method: "POST",
    body: { action: "regenerate" },
  });
  paintReview();
}

async function approveVoice() {
  if (!state.job) return;
  state.job = await api(`/api/jobs/${state.job.id}/voice/${state.lang}`, {
    method: "POST",
    body: { action: "approve" },
  });
  paintReview();
}

async function checkElevenHealth() {
  const node = $("elevenHealth");
  node.textContent = "Checking account…";
  try {
    const health = await api("/api/elevenlabs/health");
    if (health.ok) {
      const remaining = health.remaining == null ? "unknown" : Number(health.remaining).toLocaleString();
      const limit = health.character_limit ? Number(health.character_limit).toLocaleString() : "unknown";
      node.textContent = `${health.tier || "account"} · ${remaining} / ${limit} characters left · ${health.model || "model auto"}`;
      node.classList.remove("error");
    } else {
      node.textContent = health.message || "ElevenLabs account check failed.";
      node.classList.add("error");
    }
  } catch (err) {
    node.textContent = err.message;
    node.classList.add("error");
  }
}

async function produce(mode) {
  if (!state.job) {
    $("prodStage").textContent = "Draft scripts first.";
    return;
  }
  state.job = await api(`/api/jobs/${state.job.id}/produce`, {
    method: "POST",
    body: { mode },
  });
  paintProduce(state.job);
}

async function boot() {
  const data = await api("/api/bootstrap");
  state.settings = data.settings || {};
  state.languages = data.languages || [];
  state.matches = data.matches || [];
  state.capabilities = data.capabilities || {};
  paintCaps(state.capabilities);
  paintMatches(state.matches, state.settings.match_dir);
  paintLangs(state.languages, state.settings.languages);
  $("url").value = state.settings.url || "";
  $("hookClaim").value = state.settings.hook_claim || "";
  $("hookPunch").value = state.settings.hook_punch || "";
  $("bait").value = state.settings.bait_text || "";
  $("team").value = state.settings.team || "club";
  $("format").value = state.settings.format || "short";
  $("spoiler").value = state.settings.spoiler || "show";
  if ($("elevenStyle")) $("elevenStyle").value = state.settings.eleven_style || "robust";
  if ($("kids")) $("kids").checked = Boolean(state.settings.kids);
  if ($("scrapeWait")) $("scrapeWait").value = state.settings.scrape_wait || 15;
  if ($("useGemini")) $("useGemini").checked = Boolean(state.settings.use_gemini);
  if ($("geminiModel")) $("geminiModel").value = state.settings.gemini_model || "";
  if ($("star")) $("star").value = state.settings.star || "auto";
  if ($("platforms")) $("platforms").value = state.settings.platforms || "tiktok,reels,shorts";
  if ($("seriesId")) $("seriesId").value = state.settings.series_id || "";
  if ($("elevenVoice")) $("elevenVoice").value = state.settings.voice_id || "";
  if ($("elevenModel")) $("elevenModel").value = state.settings.eleven_model || "eleven_v3";
  if ($("instruction")) $("instruction").value = state.settings.instruction || "";
  if ($("visualizationCount")) $("visualizationCount").value = state.settings.visualization_count || 4;
  if ($("wordsPerSection")) $("wordsPerSection").value = state.settings.words_per_section || 17;
  if ($("targetSeconds")) $("targetSeconds").value = state.settings.target_seconds || 34;
  if ($("fps")) $("fps").value = state.settings.fps || 30;
  if ($("translationProvider")) $("translationProvider").value = state.settings.translation_provider || "auto";
  if ($("requireTranslation")) $("requireTranslation").checked = state.settings.require_context_translation !== false;
  const colors = state.settings.colors || [];
  $("colorHome").value = colors[0] || "";
  $("colorAway").value = colors[1] || "";
  if (state.settings.match_dir) {
    try {
      const resolved = await api("/api/resolve", {
        method: "POST",
        body: { match_dir: state.settings.match_dir, url: state.settings.url || "" },
      });
      if (resolved.ok) {
        applyMatch(resolved.match);
        applyColors(resolved.colors);
        await loadVisualizations(resolved.match.match_dir);
      }
    } catch (_) { /* first load without a match is fine */ }
  }
  if (state.settings.last_job_id) {
    try {
      state.job = await api(`/api/jobs/${state.settings.last_job_id}`);
      state.lang = (state.job.languages || [])[0];
      paintReview();
    } catch (_) { /* stale job files are harmless */ }
  }
}

$("btnResolve").addEventListener("click", loadMatch);
$("btnScrape").addEventListener("click", scrapeMatch);
$("btnColors").addEventListener("click", previewColors);
$("btnDraft").addEventListener("click", draft);
$("btnEdit").addEventListener("click", saveEdits);
$("btnApproveScript").addEventListener("click", approveScript);
$("btnRegen").addEventListener("click", regenVoice);
$("btnApproveVoice").addEventListener("click", approveVoice);
$("btnElevenHealth").addEventListener("click", checkElevenHealth);
$("btnPlan").addEventListener("click", () => produce("plan"));
$("btnPreviewVideo").addEventListener("click", () => produce("silent"));
$("btnProduce").addEventListener("click", () => produce("full"));
["url", "matchDir", "team", "format", "spoiler", "hookClaim", "hookPunch", "bait", "colorHome", "colorAway", "elevenStyle", "kids", "scrapeWait", "scrapeUrl", "htmlPath", "useGemini", "geminiModel", "star", "platforms", "seriesId", "elevenVoice", "elevenModel", "instruction", "visualizationCount", "wordsPerSection", "targetSeconds", "fps", "translationProvider", "requireTranslation"]
  .forEach((id) => $(id) && $(id).addEventListener("change", persist));
$("visualizationCount").addEventListener("change", async () => {
  if ($("matchDir").value) await loadVisualizations($("matchDir").value);
});
$("matchDir").addEventListener("change", loadMatch);

boot().catch((err) => { $("resolveHint").textContent = err.message; });

setInterval(() => {
  const now = new Date();
  $("clock").textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}, 1000);
