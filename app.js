const state = {
  view: "intelligence",
  matchday: null,
  matches: [],
  selectedId: null,
  selectedReport: null,
  champion: null,
  groups: [],
  calendar: [],
  bracket: [],
  tab: "analysis",
  error: null,
};

const $ = (selector) => document.querySelector(selector);

function appBasePath() {
  const scriptPath = document.currentScript?.getAttribute("src") || "";
  if (!scriptPath || scriptPath.startsWith("http")) return "";
  const normalized = scriptPath.startsWith("/") ? scriptPath : new URL(scriptPath, window.location.href).pathname;
  return normalized.endsWith("/app.js") ? normalized.slice(0, -"/app.js".length) : "";
}

const API_BASE = appBasePath();

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return `${Number(value).toFixed(1)}%`;
}

function formatTime(value, mode = "datetime") {
  if (!value) return "时间待定";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const options =
    mode === "clock"
      ? { hour: "2-digit", minute: "2-digit" }
      : { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" };
  return date.toLocaleString("zh-CN", {
    ...options,
    hour12: false,
    timeZone: "Asia/Shanghai",
  });
}

function formatRange(range) {
  if (!range?.start || !range?.end) return "最近一个有比赛的赛事日";
  return `${formatTime(range.start)} - ${formatTime(range.end)}`;
}

function flagStyle(code) {
  const gradients = {
    MEX: "linear-gradient(90deg, #77d98a 0 33%, #f7f0dc 33% 66%, #ef5b55 66%)",
    RSA: "linear-gradient(135deg, #68d282 0 34%, #e7c85e 34% 60%, #ef5b55 60%)",
    JPN: "radial-gradient(circle, #bc2031 0 34%, #f4f7fb 36%)",
    CRC: "linear-gradient(180deg, #244ca0 0 18%, #f4f7fb 18% 32%, #d92d3b 32% 68%, #f4f7fb 68% 82%, #244ca0 82%)",
    KOR: "linear-gradient(135deg, #f4f7fb, #e24b57 48%, #2f64c8 52%)",
    CZE: "linear-gradient(135deg, #2f64c8 0 42%, #f4f7fb 42% 70%, #e24b57 70%)",
    CAN: "linear-gradient(90deg, #e44b4d 0 28%, #f4f7fb 28% 72%, #e44b4d 72%)",
    GHA: "linear-gradient(180deg, #d83d38 0 33%, #f4c74f 33% 66%, #21864a 66%)",
    USA: "linear-gradient(180deg, #c83b45 0 12%, #f4f7fb 12% 24%, #c83b45 24% 36%, #f4f7fb 36% 48%, #c83b45 48% 60%, #f4f7fb 60% 72%, #c83b45 72% 84%, #f4f7fb 84%)",
    SEN: "linear-gradient(90deg, #219653 0 33%, #f4c74f 33% 66%, #d83d38 66%)",
    TUR: "linear-gradient(135deg, #d83d38, #b8202d)",
    NZL: "linear-gradient(135deg, #1d3f8f 0 70%, #d83d38 70%)",
    BRA: "radial-gradient(circle, #244ca0 0 28%, #f4c74f 30% 48%, #229b55 50%)",
    MAR: "linear-gradient(135deg, #c72f3a, #9f2430)",
    SUI: "linear-gradient(135deg, #d83d38 0 100%)",
    BIH: "linear-gradient(135deg, #3158c9 0 58%, #f1cb4f 58%)",
    ARG: "linear-gradient(180deg, #7cc7ef 0 33%, #f4f7fb 33% 66%, #7cc7ef 66%)",
    DEN: "linear-gradient(90deg, #c72f3a 0 36%, #f4f7fb 36% 46%, #c72f3a 46%)",
    PAR: "linear-gradient(180deg, #e44b4d 0 33%, #f4f7fb 33% 66%, #3158c9 66%)",
    QAT: "linear-gradient(90deg, #f4f7fb 0 32%, #7d2144 32%)",
    FRA: "linear-gradient(90deg, #244ca0 0 33%, #f4f7fb 33% 66%, #d83d38 66%)",
    CRO: "linear-gradient(180deg, #d83d38 0 33%, #f4f7fb 33% 66%, #244ca0 66%)",
    NGA: "linear-gradient(90deg, #229b55 0 33%, #f4f7fb 33% 66%, #229b55 66%)",
    PAN: "linear-gradient(135deg, #f4f7fb 0 25%, #d83d38 25% 50%, #244ca0 50% 75%, #f4f7fb 75%)",
    ESP: "linear-gradient(180deg, #c72f3a 0 25%, #f4c74f 25% 75%, #c72f3a 75%)",
    URU: "linear-gradient(180deg, #f4f7fb 0 14%, #69b9e8 14% 28%, #f4f7fb 28% 42%, #69b9e8 42% 56%, #f4f7fb 56% 70%, #69b9e8 70% 84%, #f4f7fb 84%)",
    EGY: "linear-gradient(180deg, #d83d38 0 33%, #f4f7fb 33% 66%, #181818 66%)",
    JAM: "linear-gradient(135deg, #229b55 0 38%, #f4c74f 38% 48%, #181818 48% 58%, #229b55 58%)",
    ENG: "linear-gradient(90deg, #f4f7fb 0 42%, #d83d38 42% 58%, #f4f7fb 58%)",
    COL: "linear-gradient(180deg, #f4c74f 0 50%, #244ca0 50% 75%, #d83d38 75%)",
    CIV: "linear-gradient(90deg, #f28b35 0 33%, #f4f7fb 33% 66%, #229b55 66%)",
    KSA: "linear-gradient(135deg, #178a52, #0f6b41)",
    GER: "linear-gradient(180deg, #181818 0 33%, #d83d38 33% 66%, #f4c74f 66%)",
    ECU: "linear-gradient(180deg, #f4c74f 0 50%, #244ca0 50% 75%, #d83d38 75%)",
    TUN: "radial-gradient(circle, #f4f7fb 0 36%, #d83d38 38%)",
    AUS: "linear-gradient(135deg, #1d3f8f 0 68%, #f4f7fb 68% 76%, #d83d38 76%)",
    POR: "linear-gradient(90deg, #229b55 0 42%, #d83d38 42%)",
    SRB: "linear-gradient(180deg, #d83d38 0 33%, #244ca0 33% 66%, #f4f7fb 66%)",
    ALG: "linear-gradient(90deg, #229b55 0 50%, #f4f7fb 50%)",
    PER: "linear-gradient(90deg, #d83d38 0 30%, #f4f7fb 30% 70%, #d83d38 70%)",
    NED: "linear-gradient(180deg, #d83d38 0 33%, #f4f7fb 33% 66%, #244ca0 66%)",
    CHI: "linear-gradient(180deg, #f4f7fb 0 50%, #d83d38 50%)",
    CMR: "linear-gradient(90deg, #229b55 0 33%, #d83d38 33% 66%, #f4c74f 66%)",
    IRN: "linear-gradient(180deg, #229b55 0 33%, #f4f7fb 33% 66%, #d83d38 66%)",
    BEL: "linear-gradient(90deg, #181818 0 33%, #f4c74f 33% 66%, #d83d38 66%)",
    SWE: "linear-gradient(90deg, #244ca0 0 32%, #f4c74f 32% 44%, #244ca0 44%)",
    BHR: "linear-gradient(90deg, #f4f7fb 0 34%, #e44b4d 34%)",
    NOR: "linear-gradient(90deg, #d83d38 0 28%, #f4f7fb 28% 38%, #244ca0 38% 50%, #f4f7fb 50% 60%, #d83d38 60%)",
  };
  return gradients[code] || "linear-gradient(135deg, #394b52, #5d6e73)";
}

const FLAG_CODES = {
  MEX: "mx",
  RSA: "za",
  KOR: "kr",
  CZE: "cz",
  CAN: "ca",
  BIH: "ba",
  QAT: "qa",
  SUI: "ch",
  BRA: "br",
  MAR: "ma",
  HAI: "ht",
  SCO: "gb-sct",
  USA: "us",
  PAR: "py",
  AUS: "au",
  TUR: "tr",
  GER: "de",
  CUW: "cw",
  CIV: "ci",
  ECU: "ec",
  NED: "nl",
  JPN: "jp",
  SWE: "se",
  TUN: "tn",
  BEL: "be",
  EGY: "eg",
  IRN: "ir",
  NZL: "nz",
  ESP: "es",
  CPV: "cv",
  KSA: "sa",
  URU: "uy",
  FRA: "fr",
  SEN: "sn",
  IRQ: "iq",
  NOR: "no",
  ARG: "ar",
  ALG: "dz",
  AUT: "at",
  JOR: "jo",
  POR: "pt",
  COD: "cd",
  UZB: "uz",
  COL: "co",
  ENG: "gb-eng",
  CRO: "hr",
  GHA: "gh",
  PAN: "pa",
};

function renderFlag(code) {
  const country = FLAG_CODES[code];
  if (!country) return `<span class="flag flag-fallback" title="${code || "待定"}" aria-label="${code || "待定"}"></span>`;
  return `<img class="flag" src="https://flagcdn.com/w40/${country}.png" alt="${code || "flag"}" loading="lazy" decoding="async" width="36" height="24" />`;
}

async function api(path) {
  const response = await fetch(`${API_BASE}${path}`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

async function loadInitialData() {
  try {
    const [nearest, champion, groups, calendar, bracket] = await Promise.all([
      api("/api/matches/nearest-day"),
      api("/api/tournament/champion-prediction"),
      api("/api/schedule/groups"),
      api("/api/schedule/calendar"),
      api("/api/schedule/bracket"),
    ]);
    state.matchday = nearest;
    state.matches = nearest.items || [];
    state.champion = champion;
    state.groups = groups.items || [];
    state.calendar = calendar.items || [];
    state.bracket = bracket.items || [];
    state.selectedId = state.matches[0]?.id || null;
    await loadReport();
  } catch (error) {
    state.error = error.message;
  }
  render();
}

async function loadReport() {
  state.selectedReport = state.selectedId ? await api(`/api/matches/${state.selectedId}/report`) : null;
}

function selectedMatch() {
  return state.matches.find((match) => match.id === state.selectedId) || state.matches[0] || null;
}

function renderMatchList() {
  $("#matchdayLabel").textContent = state.matchday?.label || "暂无赛事";
  $("#matchdayRange").textContent = formatRange(state.matchday?.range);
  if (state.error) {
    $("#matchList").innerHTML = `<div class="empty-state error">接口失败：${state.error}</div>`;
    return;
  }
  if (!state.matches.length) {
    $("#matchList").innerHTML = `<div class="empty-state">暂无已同步赛程，请到 Admin 后台同步。</div>`;
    return;
  }
  $("#matchList").innerHTML = state.matches
    .map((match) => {
      const active = match.id === state.selectedId ? "active" : "";
      const tags = (match.tags || [])
        .map((tag) => `<span class="tag ${tag.includes("主") || tag.includes("高") ? "gold" : ""}">${tag}</span>`)
        .join("");
      return `
        <button class="match-card ${active}" data-match="${match.id}" type="button">
          <div class="match-card-head">
            <div class="team-line">
              ${renderFlag(match.homeCode)}
              <span>${match.home} vs ${match.away}</span>
            </div>
            ${renderFlag(match.awayCode)}
          </div>
          <div class="match-time">${formatTime(match.kickoff)} · ${match.group} · ${match.venue}</div>
          <div class="tag-row">${tags}</div>
          <div class="risk-chip">
            <span>爆冷指数</span>
            <strong>${pct(match.upsetIndex)}</strong>
          </div>
        </button>
      `;
    })
    .join("");
}

function renderHero(match) {
  if (!match) {
    $("#matchMeta").textContent = "暂无赛程";
    $("#matchHeadline").textContent = "等待后端同步比赛数据";
    $("#matchSummary").textContent = "请在 Admin 后台同步赛程并生成报告。";
    $("#versusRow").innerHTML = "";
    return;
  }
  const report = state.selectedReport?.report?.content || {};
  $("#matchMeta").textContent = `${formatTime(match.kickoff)} · ${match.group} · ${match.venue} · ${match.status}`;
  $("#matchHeadline").textContent = `${match.home} vs ${match.away}`;
  $("#matchSummary").textContent = report.summary || "报告尚未发布。请在 Admin 后台生成并发布预测报告。";
  $("#versusRow").innerHTML = `
    ${renderFlag(match.homeCode)}
    <span>${match.home}</span>
    <span class="vs-token">VS</span>
    <span>${match.away}</span>
    ${renderFlag(match.awayCode)}
  `;
}

function renderProbabilities(match) {
  if (!match?.probabilities) {
    $("#probabilityList").innerHTML = `<div class="empty-state">等待生成概率。</div>`;
    $("#upsetIndex").textContent = "--";
    $("#confidenceText").textContent = "暂无模型结果。";
    return;
  }
  const rows = [
    [`${match.home}胜`, match.probabilities.home],
    ["平局", match.probabilities.draw],
    [`${match.away}胜`, match.probabilities.away],
  ];
  $("#probabilityList").innerHTML = rows
    .map(
      ([label, value]) => `
        <div class="probability-tile">
          <span>${label}</span>
          <strong>${pct(value)}</strong>
        </div>
      `,
    )
    .join("");
  $("#upsetIndex").textContent = pct(match.upsetIndex);
  $("#confidenceText").textContent = `赛前置信度 ${pct(match.confidence)}，更新时间 ${formatTime(match.updatedAt)}。`;
}

function list(items = []) {
  const normalized = normalizeList(items);
  if (!normalized.length) return `<p>暂无公布信息。</p>`;
  return `<ul>${normalized.map((item) => `<li>${item}</li>`).join("")}</ul>`;
}

function normalizeList(items) {
  if (!items) return [];
  if (Array.isArray(items)) {
    return items
      .flatMap((item) => (typeof item === "string" ? item : Object.values(item || {}).join("：")))
      .map((item) => String(item).trim())
      .filter(Boolean);
  }
  if (typeof items === "string") {
    return items
      .split(/[；;\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  if (typeof items === "object") {
    return Object.values(items)
      .flatMap((value) => normalizeList(value))
      .filter(Boolean);
  }
  return [String(items)];
}

function renderSpotlights(items = []) {
  if (!items.length) return `<div class="empty-state">球员分析待官方名单更新。</div>`;
  return `
    <section class="spotlight-panel">
      <div class="heat-line"></div>
      <h3>球员分析</h3>
      <div class="spotlight-grid">
        ${items
          .map(
            (item) => `
              <article class="spotlight-card">
                <div>
                  <strong>${item.name}</strong>
                  <span>${item.team} · ${item.role}</span>
                </div>
                <p>${item.impact}</p>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderFormationSide(lineup = {}) {
  const players = normalizePlayers(lineup.players);
  const shape = parseFormationShape(lineup.formation);
  const pitchRows = buildFormationRows(players, shape);
  return `
    <article class="formation-card">
      <div class="formation-head">
        <div>
          <h3>${lineup.team || "待确认"}</h3>
          <span>${lineup.formation || "阵型待定"} · ${lineup.confidence || "预测"}</span>
        </div>
      </div>
      <div class="pitch">
        ${pitchRows
          .map((row) => {
            return `
              <div class="pitch-line" data-line="${row.line}">
                <small>${row.label}</small>
                <div class="pitch-players" style="--slots: ${row.slots}">
                  ${row.players
                    .map(
                      (player) => `
                        <div class="player-dot">
                          <strong title="${player.fullName || player.name || "待确认"}">${player.shortName || player.name || "待确认"}</strong>
                          <span>${player.role || "位置待定"}</span>
                        </div>
                      `,
                    )
                    .join("")}
                </div>
              </div>
            `;
          })
          .join("")}
      </div>
      <p>${lineup.note || "官方首发未发布，目前为预测版。"}</p>
    </article>
  `;
}

function renderFormations(lineups = {}) {
  const statusText = lineups.note || "官方首发未发布，目前为预测版。";
  return `
    <section class="formation-panel">
      <div class="heat-line"></div>
      <div class="formation-title">
        <div>
          <h3>赛前阵容视图</h3>
          <small>按阵型层级展示，官方首发公布后自动切换为正式版</small>
        </div>
        <span class="lineup-status">${statusText}</span>
      </div>
      ${renderFullFormationPitch(lineups.home || {}, lineups.away || {})}
    </section>
  `;
}

function renderFullFormationPitch(home = {}, away = {}) {
  const homeRows = buildFormationRows(normalizePlayers(home.players), parseFormationShape(home.formation));
  const awayRows = buildFormationRows(normalizePlayers(away.players), parseFormationShape(away.formation)).reverse();
  return `
    <article class="formation-full-card">
      <div class="formation-match-head">
        ${renderFormationTeamMeta(away, "away")}
        <span>全场阵型</span>
        ${renderFormationTeamMeta(home, "home")}
      </div>
      <div class="full-pitch">
        <div class="goal-box goal-box-top"></div>
        <div class="team-half away-half">
          ${awayRows.map((row) => renderPitchRow(row, "away")).join("")}
        </div>
        <div class="center-line"><span>中线</span></div>
        <div class="team-half home-half">
          ${homeRows.map((row) => renderPitchRow(row, "home")).join("")}
        </div>
        <div class="goal-box goal-box-bottom"></div>
      </div>
      <div class="formation-notes">
        <p>${away.team || "客队"}：${away.note || "官方首发未发布，目前为预测版。"}</p>
        <p>${home.team || "主队"}：${home.note || "官方首发未发布，目前为预测版。"}</p>
      </div>
    </article>
  `;
}

function renderFormationTeamMeta(lineup = {}, side = "home") {
  return `
    <div class="formation-team-meta ${side}">
      <strong>${lineup.team || "待确认"}</strong>
      <small>${lineup.formation || "阵型待定"} · ${lineup.confidence || "预测"}</small>
    </div>
  `;
}

function renderPitchRow(row, side) {
  return `
    <div class="pitch-line ${side}" data-line="${row.line}">
      <small>${row.label}</small>
      <div class="pitch-players" style="--slots: ${row.slots}">
        ${row.players
          .map(
            (player) => `
              <div class="player-dot">
                <strong title="${player.fullName || player.name || "待确认"}">${player.shortName || player.name || "待确认"}</strong>
                <span>${player.role || "位置待定"}</span>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function normalizePlayers(players) {
  if (!Array.isArray(players)) return [];
  return players.slice(0, 11).map((player, index) => {
    const line = ["GK", "DEF", "MID", "FWD"].includes(player?.line) ? player.line : "MID";
    const role = String(player?.role || line || "位置").trim();
    const name = String(player?.name || "").trim() || role || `位置${index + 1}`;
    return { name, shortName: shortPlayerName(name), fullName: name, role: shortRole(role), line };
  });
}

function parseFormationShape(formation) {
  const parts = String(formation || "")
    .match(/\d+/g)
    ?.map((value) => Number(value))
    .filter((value) => value > 0 && value <= 5);
  if (!parts || parts.length < 2) return [4, 3, 3];
  const total = parts.reduce((sum, value) => sum + value, 0);
  return total >= 8 && total <= 10 ? parts : [4, 3, 3];
}

function buildFormationRows(players, shape) {
  const grouped = {
    GK: players.filter((player) => player.line === "GK"),
    DEF: players.filter((player) => player.line === "DEF"),
    MID: players.filter((player) => player.line === "MID"),
    FWD: players.filter((player) => player.line === "FWD"),
  };
  const rows = [];
  const defenseSlots = shape[0] || 4;
  const forwardSlots = shape[shape.length - 1] || 1;
  const midfieldSlots = shape.slice(1, -1);

  rows.push(makeFormationRow("FWD", labelForAttack(forwardSlots), forwardSlots, takePlayers([grouped.FWD, grouped.MID, grouped.DEF], forwardSlots)));
  midfieldSlots
    .slice()
    .reverse()
    .forEach((slots, index, arr) => {
      rows.push(makeFormationRow("MID", labelForMidfield(index, arr.length), slots, takePlayers([grouped.MID, grouped.FWD, grouped.DEF], slots)));
    });
  rows.push(makeFormationRow("DEF", "防线", defenseSlots, takePlayers([grouped.DEF, grouped.MID, grouped.FWD], defenseSlots)));
  rows.push(makeFormationRow("GK", "门将", 1, takePlayers([grouped.GK], 1)));
  return rows;
}

function takePlayers(pools, slots) {
  const picked = [];
  pools.forEach((pool) => {
    while (picked.length < slots && pool.length) {
      picked.push(pool.shift());
    }
  });
  while (picked.length < slots) {
    picked.push({ name: "待确认", shortName: "待确认", fullName: "待确认", role: "赛前更新" });
  }
  return picked;
}

function makeFormationRow(line, label, slots, players) {
  return { line, label, slots, players };
}

function labelForAttack(slots) {
  return slots > 1 ? "锋线" : "中锋";
}

function labelForMidfield(index, total) {
  if (total <= 1) return "中场";
  if (index === 0) return "前场";
  if (index === total - 1) return "后腰";
  return "中场";
}

function shortPlayerName(name) {
  const cleaned = String(name || "").trim();
  if (!cleaned) return "待确认";
  const separators = ["·", " ", "-", "・"];
  for (const separator of separators) {
    if (cleaned.includes(separator)) {
      const parts = cleaned.split(separator).map((part) => part.trim()).filter(Boolean);
      const last = parts[parts.length - 1] || cleaned;
      return last.length > 5 ? last.slice(0, 5) : last;
    }
  }
  return cleaned.length > 5 ? `${cleaned.slice(0, 5)}` : cleaned;
}

function shortRole(role) {
  const text = String(role || "").trim();
  const map = {
    防守中场: "后腰",
    攻击中场: "前腰",
    中后卫: "中卫",
  };
  return map[text] || (text.length > 4 ? text.slice(0, 4) : text);
}

function renderScoreAndTotals(content = {}) {
  const score = content.score_prediction || {};
  const totals = content.totals_prediction || {};
  const totalPick = totals.displayPick || (totals.pick === "大球" ? "进球偏多" : totals.pick === "小球" ? "进球偏少" : "--");
  return `
    <div class="market-grid">
      <article class="market-card">
        <div class="heat-line"></div>
        <h3>比分预测</h3>
        <strong>${score.primary || "--"}</strong>
        <p>${score.analysis || "比分预测待模型生成。"}</p>
        <div class="mini-meta">
          <span>备选 ${score.alternatives?.join(" / ") || "--"}</span>
        </div>
      </article>
      <article class="market-card">
        <div class="heat-line"></div>
        <h3>进球数倾向</h3>
        <strong>${totalPick}</strong>
        <p>${totals.analysis || "进球数倾向待球队攻防信息更新后生成。"}</p>
      </article>
    </div>
  `;
}

function signedValue(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(1)}`;
}

function factorValue(factor = {}) {
  const name = String(factor.name || "");
  if (name.includes("进球") || name.includes("比分") || name.includes("Poisson")) {
    const left = factor.homeImpact === null || factor.homeImpact === undefined ? "--" : Number(factor.homeImpact).toFixed(1);
    const right = factor.awayImpact === null || factor.awayImpact === undefined ? "--" : Number(factor.awayImpact).toFixed(1);
    return `${left} / ${right}`;
  }
  return `${signedValue(factor.homeImpact)} / ${signedValue(factor.awayImpact)}`;
}

function boundedPercent(value, fallback = 0) {
  const number = Number(value);
  if (Number.isNaN(number)) return fallback;
  return Math.max(0, Math.min(100, number));
}

function factorTeams(report = {}) {
  const match = state.selectedReport?.match || report.match || {};
  return {
    home: match.home || match.home_name || "主队",
    away: match.away || match.away_name || "客队",
  };
}

function isGoalTrendFactor(factor = {}) {
  const name = String(factor.name || "");
  return name.includes("进球") || name.includes("比分") || name.includes("Poisson") || name.includes("杩涚悆") || name.includes("姣斿垎");
}

function renderRelativeFactorBar(factor = {}, teams = {}) {
  const homeImpact = Number(factor.homeImpact || 0);
  const awayImpact = Number(factor.awayImpact || 0);
  const homeWidth = boundedPercent(50 + homeImpact, 50);
  const awayWidth = 100 - homeWidth;
  const leader = Math.abs(homeImpact) < 0.05 ? "双方接近" : homeImpact > 0 ? `${teams.home}占优` : `${teams.away}占优`;
  const edge = Math.max(Math.abs(homeImpact), Math.abs(awayImpact));
  const edgeText = edge ? ` +${edge.toFixed(1)}` : "";
  return `
    <div class="factor-bar factor-bar-relative" aria-label="${factor.name} ${leader}">
      <span class="factor-fill home" style="width:${homeWidth}%"></span>
      <span class="factor-fill away" style="width:${awayWidth}%"></span>
      <i></i>
    </div>
    <div class="factor-meta">
      <span>${teams.home}</span>
      <strong>${leader}${edgeText}</strong>
      <span>${teams.away}</span>
    </div>
  `;
}

function renderGoalTrendBar(factor = {}, report = {}, teams = {}) {
  const prediction = report.prediction || {};
  const home = boundedPercent(prediction.home_win ?? factor.homeImpact, 0);
  const away = boundedPercent(prediction.away_win ?? factor.awayImpact, 0);
  const draw = boundedPercent(prediction.draw, Math.max(0, 100 - home - away));
  const total = home + draw + away || 100;
  return `
    <div class="factor-bar factor-bar-prob" aria-label="${factor.name} 胜平负概率">
      <span class="factor-fill home" style="width:${(home / total) * 100}%"></span>
      <span class="factor-fill draw" style="width:${(draw / total) * 100}%"></span>
      <span class="factor-fill away" style="width:${(away / total) * 100}%"></span>
    </div>
    <div class="factor-meta factor-meta-prob">
      <span>${teams.home} ${home.toFixed(1)}%</span>
      <strong>平 ${draw.toFixed(1)}%</strong>
      <span>${teams.away} ${away.toFixed(1)}%</span>
    </div>
  `;
}

function renderFactorVisual(factor = {}, report = {}) {
  const teams = factorTeams(report);
  return isGoalTrendFactor(factor) ? renderGoalTrendBar(factor, report, teams) : renderRelativeFactorBar(factor, teams);
}

function attrText(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

let activeHelpTarget = null;
let helpTooltip = null;

function ensureHelpTooltip() {
  if (helpTooltip) return helpTooltip;
  helpTooltip = document.createElement("div");
  helpTooltip.className = "floating-tooltip";
  helpTooltip.id = "floatingHelpTooltip";
  helpTooltip.setAttribute("role", "tooltip");
  document.body.appendChild(helpTooltip);
  return helpTooltip;
}

function hideHelpTooltip() {
  if (activeHelpTarget) {
    activeHelpTarget.removeAttribute("aria-describedby");
    activeHelpTarget.setAttribute("aria-expanded", "false");
  }
  activeHelpTarget = null;
  if (helpTooltip) {
    helpTooltip.classList.remove("visible");
    helpTooltip.hidden = true;
  }
}

function positionHelpTooltip(target) {
  const tooltip = ensureHelpTooltip();
  const margin = 12;
  const targetRect = target.getBoundingClientRect();
  const viewportWidth = document.documentElement.clientWidth;
  const viewportHeight = document.documentElement.clientHeight;

  tooltip.style.maxWidth = `${Math.max(220, viewportWidth - margin * 2)}px`;
  tooltip.style.left = "0px";
  tooltip.style.top = "0px";
  tooltip.hidden = false;

  const tooltipRect = tooltip.getBoundingClientRect();
  const maxLeft = Math.max(margin, viewportWidth - tooltipRect.width - margin);
  const preferredLeft = targetRect.left + targetRect.width / 2 - tooltipRect.width / 2;
  const left = Math.min(Math.max(preferredLeft, margin), maxLeft);

  const belowTop = targetRect.bottom + 10;
  const aboveTop = targetRect.top - tooltipRect.height - 10;
  const useAbove = belowTop + tooltipRect.height > viewportHeight - margin && aboveTop >= margin;
  const top = useAbove ? aboveTop : Math.min(belowTop, Math.max(margin, viewportHeight - tooltipRect.height - margin));

  tooltip.dataset.placement = useAbove ? "top" : "bottom";
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function showHelpTooltip(target) {
  const text = target?.dataset?.tooltip || "";
  if (!text) return;
  const tooltip = ensureHelpTooltip();
  tooltip.textContent = text;
  activeHelpTarget?.setAttribute("aria-expanded", "false");
  activeHelpTarget = target;
  target.setAttribute("aria-describedby", tooltip.id);
  target.setAttribute("aria-expanded", "true");
  positionHelpTooltip(target);
  requestAnimationFrame(() => tooltip.classList.add("visible"));
}

function cleanLogicText(text) {
  const banned = [
    "Elo",
    "Poisson",
    "Dixon",
    "模型",
    "校准",
    "稳定器",
    "外部信号",
    "基础分数",
    "基础评分差",
    "归一化",
    "分数分布",
    "确定性结论",
    "隐含概率",
    "多模型",
    "置信度",
  ];
  return String(text || "")
    .replaceAll("；", "。")
    .split("。")
    .map((part) => part.trim())
    .filter((part) => part && !banned.some((term) => part.includes(term)))
    .join("。")
    .trim();
}

function calculationMethodNote(content = {}, report = {}) {
  const fallback = "计算采用分层集成：Elo/基础评分处理长期强度，近期状态处理短期动量，攻防匹配比较进攻和防守稳定性，Poisson/Dixon-Coles比分层校验进球分布，外部校准信号只作为概率稳定器，最后用多模型分歧和足球随机性调整置信度。概率适合理解为赛前分布，不是确定性结论。";
  return content.calculation_method_note || report.prediction?.methodology?.deepseek_rule || fallback;
}

function publicFactor(factor = {}) {
  const rawName = String(factor.name || "");
  if (rawName.includes("综合校准") || rawName.includes("不确定性")) return null;
  const name = rawName
    .replace("Elo基础评分", "基础评分")
    .replace("Poisson比分层", "进球走势")
    .replace("比分层", "进球走势");
  const defaultDetails = {
    基础评分: "整体强度与赛地因素的综合对比。",
    近期状态: "近期表现和进入比赛状态的对比。",
    攻防匹配: "推进质量与防守承压能力的对比。",
    进球走势: "结合攻防效率后的比分区间参考。",
  };
  const rawDetail = String(factor.detail || "");
  const detail = cleanLogicText(rawDetail) || defaultDetails[name] || "";
  return { ...factor, name, detail };
}

function factorTooltip(factor = {}) {
  const name = String(factor.name || "");
  if (name.includes("基础评分")) {
    return "由球队长期强度评分、基础实力档位和主客/赛地修正组成；不等同于球队身价，暂未直接接入实时球员身价。";
  }
  if (name.includes("近期状态")) {
    return "由近期状态分、比赛强度、进入比赛节奏的速度等短期动量组成。";
  }
  if (name.includes("攻防匹配")) {
    return "由本队进攻推进质量与对手防守承压能力组合而成，体现一方进攻是否刚好打到另一方弱点。";
  }
  if (name.includes("进球走势")) {
    return "由双方攻防效率推导预期进球，再转换为胜平负概率和首选比分区间；这里显示的是概率条，不是相对差值。";
  }
  return "该项为赛前模型因子，用于解释胜平负概率的主要来源。";
}

function renderFactorTitle(factor = {}) {
  const tooltip = attrText(factorTooltip(factor));
  return `<div class="factor-title"><strong>${factor.name}</strong><button class="method-help factor-help" type="button" aria-label="查看${factor.name}组成说明" data-tooltip="${tooltip}">?</button></div>`;
}

function renderModelLogic(content = {}, report = {}) {
  const factors = (report.factors || []).map(publicFactor).filter(Boolean);
  const logicText = cleanLogicText(content.logic) || "胜负逻辑待模型生成。";
  const methodNote = attrText(calculationMethodNote(content, report));
  return `
    <section class="model-logic-panel">
      <div class="heat-line"></div>
      <div class="model-logic-head">
        <div>
          <h3>胜负逻辑 <button class="method-help" type="button" aria-label="查看模型计算说明" data-tooltip="${methodNote}">?</button></h3>
        </div>
        <span>赛前判断</span>
      </div>
      <p class="model-logic-text">${logicText}</p>
      ${
        factors.length
          ? `<div class="model-factor-grid" aria-label="评分比较">
              ${factors
                .map(
                  (factor) => `
                    <article>
                      ${renderFactorTitle(factor)}
                      ${renderFactorVisual(factor, report)}
                      <p>${factor.detail || ""}</p>
                    </article>
                  `,
                )
                .join("")}
            </div>`
          : ""
      }
    </section>
  `;
}

function renderAnalysis() {
  const content = state.selectedReport?.report?.content;
  if (!content) return `<div class="empty-state">本场报告未发布。请在 Admin 后台生成并发布。</div>`;
  const report = state.selectedReport?.report || {};
  return `
    <section class="source-card analysis-lead">
      <h3>核心判断</h3>
      <p>${content.summary || "暂无结论。"}</p>
    </section>
    ${renderSpotlights(content.player_spotlight || [])}
    ${renderModelLogic(content, report)}
    ${renderScoreAndTotals(content)}
    <div class="insight-grid">
      <article class="insight-card"><div class="heat-line"></div><h3>赢球路径</h3>${list(content.win_path)}</article>
      <article class="insight-card"><div class="heat-line"></div><h3>丢分风险</h3>${list(content.risk_points)}</article>
      <article class="insight-card"><div class="heat-line"></div><h3>关键对位</h3>${list(content.key_matchups)}</article>
      <article class="insight-card"><div class="heat-line"></div><h3>关键球员表现</h3>${list(content.player_performance || [])}</article>
      <article class="insight-card"><div class="heat-line"></div><h3>比赛节奏</h3>${list(content.match_conditions || [])}</article>
      <article class="insight-card"><div class="heat-line"></div><h3>爆冷条件</h3>${list(content.upset_conditions || [])}</article>
    </div>
  `;
}

function renderPlayers() {
  const content = state.selectedReport?.report?.content;
  if (!content) return `<div class="empty-state">球员状态待报告发布后显示。</div>`;
  const status = content.player_status || {};
  const notes = content.lineup_notes || {};
  const blocks = [
    ["主队", status.home, notes.home],
    ["客队", status.away, notes.away],
  ];
  return `
    ${renderFormations(content.lineups || {})}
    <div class="insight-grid">
      ${blocks
        .map(
          ([label, teamStatus, note]) => `
            <article class="insight-card">
              <div class="heat-line"></div>
              <h3>${label} · ${teamStatus?.team || "待确认"}</h3>
              <h4>伤停</h4>${list(teamStatus?.injuries || [])}
              <h4>疑似缺阵</h4>${list(teamStatus?.doubtful || [])}
              <h4>关键球员</h4>${list(teamStatus?.key_players || [])}
              <p class="lineup-note">${note || "预计首发待官方阵容发布后更新。"}</p>
            </article>
          `,
        )
        .join("")}
    </div>
    <section class="source-card"><h3>阵容不确定性</h3><p>${notes.uncertainty || "首发、伤停和临场轮换会显著影响最终概率。"}</p></section>
  `;
}

function renderConditions() {
  const content = state.selectedReport?.report?.content;
  if (!content) return `<div class="empty-state">赛前条件待报告发布后显示。</div>`;
  return `
    <div class="insight-grid">
      <article class="insight-card"><div class="heat-line"></div><h3>赛前条件</h3>${list(content.match_conditions || [])}</article>
      <article class="insight-card"><div class="heat-line"></div><h3>爆冷条件</h3>${list(content.upset_conditions || [])}</article>
      <article class="insight-card"><div class="heat-line"></div><h3>伤停影响</h3><p>${content.injury_impact || "暂无可靠公开信息。"}</p></article>
      <article class="insight-card"><div class="heat-line"></div><h3>可信度提示</h3><p>${content.data_confidence_note || "赛前阵容公布后建议重新生成最终版。"}</p></article>
    </div>
  `;
}

function renderTab() {
  const views = {
    analysis: renderAnalysis,
    players: renderPlayers,
    conditions: renderConditions,
  };
  $("#tabContent").innerHTML = views[state.tab]();
}

function renderChampionView() {
  const items = state.champion?.items || [];
  const top = items[0];
  $("#championSummary").innerHTML = items.length
    ? `
      <article class="summary-tile"><strong>${items.length}</strong><span>参评球队</span></article>
      <article class="summary-tile"><strong>${top.team}</strong><span>当前榜首</span></article>
      <article class="summary-tile"><strong>${pct(top.championProbability)}</strong><span>冠军概率</span></article>
    `
    : "";
  const tierOrder = ["争冠热门", "四强竞争者", "潜在黑马", "小组出线优先"];
  $("#championList").innerHTML = items.length
    ? tierOrder
        .map((tierName) => {
          const tierItems = items.filter((item) => (item.tier || "小组出线优先") === tierName);
          if (!tierItems.length) return "";
          return `
            <section class="champion-tier">
              <div class="tier-head">
                <h2>${tierName}</h2>
                <span>${tierItems.length} 支球队</span>
              </div>
              <div class="tier-list">
                ${tierItems
                  .map((item) => {
                    const index = items.indexOf(item);
                    return `
                      <article class="champion-row">
                        <span class="rank">${index + 1}</span>
                        ${renderFlag(item.code)}
                        <div class="champion-team">
                          <div class="champion-team-head">
                            <strong>${item.team}</strong>
                            <span>${pct(item.championProbability)}</span>
                          </div>
                          <div class="champion-model">
                            <h3>评分模型</h3>
                            <div class="champion-model-grid">
                              ${(item.modelSummary || fallbackChampionModelSummary(item))
                                .map((factor) => `<span><em>${factor.label}</em><strong>${factor.value}</strong></span>`)
                                .join("")}
                            </div>
                          </div>
                          <div class="champion-analysis">
                            <h3>分析</h3>
                            <p>${item.analysis || "综合实力和晋级路径仍需结合赛前信息更新。"}</p>
                          </div>
                        </div>
                      </article>
                    `;
                  })
                  .join("")}
              </div>
            </section>
          `;
        })
        .join("")
    : `<div class="empty-state">冠军预测尚未生成。</div>`;
}

function fallbackChampionModelSummary(item) {
  return [
    { label: "综合概率", value: pct(item.championProbability) },
    { label: "模型概率", value: pct(item.modelProbability) },
    { label: "球队评分", value: item.modelFactors?.rating ? Number(item.modelFactors.rating).toFixed(0) : "--" },
    { label: "近期状态", value: item.modelFactors?.form ? Number(item.modelFactors.form).toFixed(1) : "--" },
    { label: "进攻评分", value: item.modelFactors?.attack ? Number(item.modelFactors.attack).toFixed(1) : "--" },
    { label: "防守评分", value: item.modelFactors?.defense ? Number(item.modelFactors.defense).toFixed(1) : "--" },
  ];
}

function renderScheduleView() {
  const teamCount = state.groups.reduce((sum, group) => sum + group.teams.length, 0);
  const matchCount = state.calendar.reduce((sum, day) => sum + day.items.length, 0);
  $("#scheduleSummary").innerHTML = `
    <article class="summary-tile"><strong>${state.groups.length}</strong><span>小组</span></article>
    <article class="summary-tile"><strong>${teamCount}</strong><span>球队</span></article>
    <article class="summary-tile"><strong>${matchCount}</strong><span>已排赛程</span></article>
  `;
  $("#groupList").innerHTML = state.groups
    .map(
      (group) => `
        <article class="group-card">
          <div class="group-card-head">
            <h3>${group.group}</h3>
            <span>${group.teams.length} 支球队</span>
          </div>
          <div class="group-standings">
            <div class="standing-head">
              <span></span><span></span><span>总赛</span><span>胜</span><span>平</span><span>负</span><span>积分</span>
            </div>
            ${group.teams
              .map(
                (team) => `
                  <div class="standing-row">
                    ${renderFlag(team.code)}
                    <strong>${team.name}</strong>
                    <span>${team.played ?? 0}</span>
                    <span>${team.wins ?? 0}</span>
                    <span>${team.draws ?? 0}</span>
                    <span>${team.losses ?? 0}</span>
                    <span>${team.points ?? 0}</span>
                  </div>
                `,
              )
              .join("")}
          </div>
        </article>
      `,
    )
    .join("");
  $("#calendarList").innerHTML = state.calendar
    .map(
      (day) => `
        <article class="calendar-day">
          <div class="calendar-head">
            <h3>${day.label}</h3>
            <span>${day.items.length} 场</span>
          </div>
          ${day.items.map((match) => `
            <div class="calendar-match">
              <span class="time-badge">${formatTime(match.kickoff, "clock")}</span>
              <strong>${renderFlag(match.homeCode)}${match.home}<em>VS</em>${match.away}${renderFlag(match.awayCode)}</strong>
              <small>${match.group} · ${match.venue}</small>
            </div>
          `).join("")}
        </article>
      `,
    )
    .join("");
  $("#bracketList").innerHTML = state.bracket
    .map(
      (round) => `
        <article class="bracket-round">
          <h3>${round.round}</h3>
          ${round.ties.map((tie) => `<div class="bracket-tie"><span>${tie.slot}</span><strong>${tie.home}</strong><em>vs</em><strong>${tie.away}</strong></div>`).join("")}
        </article>
      `,
    )
    .join("");
}

function syncTabs() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === state.tab);
  });
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === state.view);
  });
  document.querySelectorAll(".view-panel").forEach((panel) => {
    panel.hidden = panel.id !== `${state.view}View`;
  });
}

function render() {
  hideHelpTooltip();
  const match = selectedMatch();
  renderMatchList();
  renderHero(match);
  renderProbabilities(match);
  renderTab();
  renderScheduleView();
  renderChampionView();
  syncTabs();
}

document.querySelector("#matchList").addEventListener("click", async (event) => {
  const button = event.target.closest(".match-card");
  if (!button) return;
  state.selectedId = button.dataset.match;
  state.tab = "analysis";
  state.error = null;
  try {
    await loadReport();
  } catch (error) {
    state.error = error.message;
  }
  render();
});

document.querySelector(".tab-row").addEventListener("click", (event) => {
  const button = event.target.closest(".tab-button");
  if (!button) return;
  state.tab = button.dataset.tab;
  render();
});

document.querySelector(".main-nav").addEventListener("click", (event) => {
  const button = event.target.closest(".nav-button");
  if (!button) return;
  state.view = button.dataset.view;
  render();
});

document.addEventListener("click", (event) => {
  const clickedHelp = event.target.closest?.(".method-help");
  if (clickedHelp) {
    event.preventDefault();
    clickedHelp.focus({ preventScroll: true });
    showHelpTooltip(clickedHelp);
    return;
  }
  hideHelpTooltip();
});

document.addEventListener("focusin", (event) => {
  const help = event.target.closest?.(".method-help");
  if (help) {
    showHelpTooltip(help);
  } else {
    hideHelpTooltip();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  hideHelpTooltip();
  document.activeElement?.blur?.();
});

window.addEventListener("resize", () => {
  if (activeHelpTarget) positionHelpTooltip(activeHelpTarget);
});

window.addEventListener("scroll", () => {
  if (activeHelpTarget && document.body.contains(activeHelpTarget)) {
    positionHelpTooltip(activeHelpTarget);
  }
}, { passive: true });

document.addEventListener("pointerover", (event) => {
  if (event.pointerType !== "mouse") return;
  const help = event.target.closest?.(".method-help");
  if (help) showHelpTooltip(help);
});

document.addEventListener("pointerout", (event) => {
  if (event.pointerType !== "mouse") return;
  const help = event.target.closest?.(".method-help");
  if (!help || help.contains(event.relatedTarget)) return;
  hideHelpTooltip();
});

loadInitialData();
