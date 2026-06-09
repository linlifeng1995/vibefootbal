const adminState = {
  token: localStorage.getItem("wc-admin-token") || "change-me",
};

const adminLogin = document.querySelector("#adminLogin");
const adminShell = document.querySelector("#adminShell");
const adminPassword = document.querySelector("#adminPassword");
const adminLoginButton = document.querySelector("#adminLoginButton");
const adminLoginMessage = document.querySelector("#adminLoginMessage");
const adminLog = document.querySelector("#adminLog");
const tokenInput = document.querySelector("#adminToken");
const progressPanel = document.querySelector("#adminProgress");
const progressText = document.querySelector("#adminProgressText");
const progressBar = document.querySelector("#adminProgressBar");
const progressDetail = document.querySelector("#adminProgressDetail");
const dataStatusList = document.querySelector("#dataStatusList");
const jobList = document.querySelector("#jobList");
const wechatMatchday = document.querySelector("#wechatMatchday");
const wechatArticleList = document.querySelector("#wechatArticleList");
const wechatArticlePreview = document.querySelector("#wechatArticlePreview");
const wechatPreviewTitle = document.querySelector("#wechatPreviewTitle");
const wechatPreviewMeta = document.querySelector("#wechatPreviewMeta");
const wechatMarkdownPreview = document.querySelector("#wechatMarkdownPreview");
const wechatHtmlPreview = document.querySelector("#wechatHtmlPreview");
const wechatPreviewError = document.querySelector("#wechatPreviewError");
const pushWechatDraft = document.querySelector("#pushWechatDraft");
const generateWechatDaily = document.querySelector("#generateWechatDaily");
const refreshWechatArticles = document.querySelector("#refreshWechatArticles");
let selectedWechatArticleId = null;
tokenInput.value = adminState.token;

function appBasePath() {
  const scriptPath = document.currentScript?.getAttribute("src") || "";
  if (!scriptPath || scriptPath.startsWith("http")) return "";
  const normalized = scriptPath.startsWith("/") ? scriptPath : new URL(scriptPath, window.location.href).pathname;
  return normalized.endsWith("/admin.js") ? normalized.slice(0, -"/admin.js".length) : "";
}

const API_BASE = appBasePath();

function writeLog(value) {
  adminLog.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function setProgress(current, total, detail = "", displayText = null) {
  const percent = total ? Math.round((current / total) * 100) : 0;
  progressPanel.hidden = false;
  progressText.textContent = displayText || `${Math.floor(current)} / ${total}`;
  progressBar.style.width = `${percent}%`;
  progressDetail.textContent = detail || "正在生成赛前情报。";
}

function resetProgress() {
  progressPanel.hidden = true;
  progressText.textContent = "0 / 0";
  progressBar.style.width = "0%";
  progressDetail.textContent = "等待开始。";
}

function setBusy(button, busy, label = "处理中...") {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.textContent;
    button.textContent = label;
    button.disabled = true;
    return;
  }
  button.textContent = button.dataset.originalText || button.textContent;
  button.disabled = false;
}

async function adminFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": adminState.token,
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  return data;
}

async function publicFetch(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `HTTP ${response.status}`);
  }
  return data;
}

function showAdminShell() {
  adminLogin.hidden = true;
  adminShell.hidden = false;
}

function showAdminLogin(message = "通过后还需要 Admin Token 才能执行管理操作。") {
  adminShell.hidden = true;
  adminLogin.hidden = false;
  adminLoginMessage.textContent = message;
  adminPassword.focus();
}

async function checkAdminPageSession() {
  try {
    const data = await publicFetch("/api/admin/page-session");
    if (data.authenticated) {
      showAdminShell();
      await loadAdminDashboard();
      return;
    }
  } catch (error) {
    showAdminLogin(error.message);
    return;
  }
  showAdminLogin();
}

async function loadAdminDashboard() {
  await Promise.all([loadDataStatus(), loadJobs(), loadMatches(), loadWechatMatchdays(), loadWechatArticles(), loadLogs()]);
  resetProgress();
}

function statusLabel(status) {
  const labels = { ok: "正常", success: "成功", running: "运行中", waiting: "等待中", idle: "空闲", stale: "待更新", missing: "缺失", error: "失败" };
  return labels[status] || status || "未知";
}

function formatAdminTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function padTime(value) {
  return String(value ?? 0).padStart(2, "0");
}

async function loadDataStatus() {
  try {
    const data = await adminFetch("/api/admin/data-status");
    dataStatusList.innerHTML = data.items.length
      ? data.items
          .map(
            (item) => `
              <article class="admin-status-item ${item.status}">
                <span>${statusLabel(item.status)}</span>
                <strong>${item.label}</strong>
                <small>${formatAdminTime(item.updated_at)}</small>
                <p>${item.summary || "暂无摘要"}</p>
              </article>
            `,
          )
          .join("")
      : `<div class="empty-state">暂无数据状态。</div>`;
  } catch (error) {
    dataStatusList.innerHTML = `<div class="empty-state error">${error.message}</div>`;
  }
}

async function loadJobs() {
  try {
    const data = await adminFetch("/api/admin/jobs");
    jobList.innerHTML = data.items.length
      ? data.items
          .map(
            (job) => `
              <article class="admin-job ${job.status}">
                <div>
                  <span>${statusLabel(job.status)}</span>
                  <strong>${job.name}</strong>
                  <p>${job.description}</p>
                </div>
                <dl>
                  <div><dt>计划</dt><dd>${job.trigger}</dd></div>
                  <div><dt>上次</dt><dd>${formatAdminTime(job.lastRunAt)}</dd></div>
                  <div><dt>下次</dt><dd>${formatAdminTime(job.nextRunAt)}</dd></div>
                  <div><dt>耗时</dt><dd>${job.lastDurationSeconds ? `${Number(job.lastDurationSeconds).toFixed(1)}s` : "暂无"}</dd></div>
                </dl>
                <small>${job.lastMessage || "尚未运行"}</small>
                <form class="admin-job-config" data-job-config="${job.id}">
                  <label>
                    <span>模式</span>
                    <select name="mode">
                      <option value="daily" ${job.config?.mode === "daily" ? "selected" : ""}>每天定时</option>
                      <option value="interval" ${job.config?.mode === "interval" ? "selected" : ""}>间隔时间</option>
                    </select>
                  </label>
                  <label>
                    <span>时间</span>
                    <input name="time" type="time" value="${padTime(job.config?.hour)}:${padTime(job.config?.minute)}" />
                  </label>
                  <label>
                    <span>间隔分钟</span>
                    <input name="interval" type="number" min="5" max="1440" step="5" value="${job.config?.interval_minutes || 30}" />
                  </label>
                  <label class="admin-job-toggle">
                    <input name="enabled" type="checkbox" ${job.config?.enabled === false ? "" : "checked"} />
                    <span>启用</span>
                  </label>
                  <div class="admin-job-actions">
                    <button data-save-job="${job.id}" type="submit">保存计划</button>
                    <button data-run-job="${job.id}" type="button">立即运行</button>
                  </div>
                </form>
              </article>
            `,
          )
          .join("")
      : `<div class="empty-state">暂无定时任务。</div>`;
  } catch (error) {
    jobList.innerHTML = `<div class="empty-state error">${error.message}</div>`;
  }
}

function readJobConfig(form) {
  const data = new FormData(form);
  const mode = data.get("mode");
  const enabled = data.get("enabled") === "on";
  if (mode === "daily") {
    const [hour, minute] = String(data.get("time") || "00:00").split(":").map((value) => Number(value));
    return { mode, hour, minute, enabled };
  }
  return { mode, interval_minutes: Number(data.get("interval") || 30), enabled };
}

async function loadMatches() {
  try {
    const data = await adminFetch("/api/admin/matches");
    document.querySelector("#adminMatches").innerHTML = data.items
      .map(
        (match) => `
          <article class="admin-match">
            <div>
              <strong>${match.home} vs ${match.away}</strong>
              <span>${match.kickoff}</span>
              <small>预测：${match.prediction_generated_at || "未生成"} · 发布：${match.published_report_id || "未发布"}</small>
            </div>
            <div class="admin-buttons">
              <button data-research="${match.id}" type="button">检索</button>
              <button data-generate="${match.id}" type="button">生成</button>
            </div>
          </article>
        `,
      )
      .join("");
  } catch (error) {
    writeLog(error.message);
  }
}

function wechatStatusLabel(status) {
  const labels = {
    generated: "已生成",
    fact_failed: "校验失败",
    draft_pushed: "已推草稿",
    failed: "失败",
  };
  return labels[status] || status || "未知";
}

function formatMatchdayRange(range) {
  if (!range?.start || !range?.end) return "";
  return `${formatAdminTime(range.start)} - ${formatAdminTime(range.end)}`;
}

async function loadWechatMatchdays() {
  try {
    const currentValue = wechatMatchday.value;
    const data = await adminFetch("/api/admin/matchdays");
    wechatMatchday.innerHTML = data.items.length
      ? data.items
          .map((item) => {
            const label = `${item.label} · ${item.count} 场 · ${formatMatchdayRange(item.range)}`;
            return `<option value="${item.matchday}">${label}</option>`;
          })
          .join("")
      : `<option value="">暂无可生成的比赛日</option>`;
    if (currentValue && data.items.some((item) => item.matchday === currentValue)) {
      wechatMatchday.value = currentValue;
    }
    wechatMatchday.disabled = !data.items.length;
    generateWechatDaily.disabled = !data.items.length;
  } catch (error) {
    wechatMatchday.innerHTML = `<option value="">比赛日加载失败</option>`;
    wechatMatchday.disabled = true;
    generateWechatDaily.disabled = true;
    writeLog(error.message);
  }
}

async function loadWechatArticles() {
  try {
    const data = await adminFetch("/api/admin/wechat/articles");
    wechatArticleList.innerHTML = data.items.length
      ? data.items
          .map(
            (article) => `
              <article class="admin-match wechat-article ${article.status}">
                <div>
                  <strong>${article.title}</strong>
                  <span>${article.matchday} · v${article.version} · ${wechatStatusLabel(article.status)}</span>
                  <small>${article.digest || "暂无摘要"}</small>
                  ${article.errorMessage ? `<p class="empty-state error">${article.errorMessage}</p>` : ""}
                </div>
                <div class="admin-buttons">
                  <button data-wechat-preview="${article.id}" type="button">预览</button>
                  <button data-wechat-push="${article.id}" type="button" ${article.status === "draft_pushed" || article.status === "fact_failed" ? "disabled" : ""}>推草稿</button>
                </div>
              </article>
            `,
          )
          .join("")
      : `<div class="empty-state">暂无公众号文章。</div>`;
  } catch (error) {
    wechatArticleList.innerHTML = `<div class="empty-state error">${error.message}</div>`;
  }
}

async function loadWechatArticleDetail(articleId) {
  const article = await adminFetch(`/api/admin/wechat/articles/${articleId}`);
  selectedWechatArticleId = article.id;
  wechatArticlePreview.hidden = false;
  wechatPreviewTitle.textContent = article.title;
  wechatPreviewMeta.textContent = `${article.matchday} · v${article.version} · ${wechatStatusLabel(article.status)} · ${formatAdminTime(article.createdAt)}`;
  wechatMarkdownPreview.textContent = article.markdown || "";
  wechatHtmlPreview.innerHTML = article.wechatHtml || "";
  wechatPreviewError.hidden = !article.errorMessage;
  wechatPreviewError.textContent = article.errorMessage || "";
  pushWechatDraft.disabled = article.status === "draft_pushed" || article.status === "fact_failed";
  return article;
}

async function generateWechatDailyPreview() {
  if (!wechatMatchday.value) throw new Error("请先选择一个比赛日。");
  const payload = {
    matchday: wechatMatchday.value,
    force: true,
  };
  const result = await adminFetch("/api/admin/wechat/daily-preview/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  await loadWechatArticles();
  await loadWechatArticleDetail(result.id);
  return result;
}

async function pushSelectedWechatDraft(articleId = selectedWechatArticleId) {
  if (!articleId) throw new Error("请先选择一篇公众号文章。");
  const result = await adminFetch(`/api/admin/wechat/articles/${articleId}/push-draft`, { method: "POST" });
  await loadWechatArticles();
  await loadWechatArticleDetail(articleId);
  return result;
}

async function loadLogs() {
  try {
    const data = await adminFetch("/api/admin/logs?limit=60");
    document.querySelector("#adminLog").textContent = data.items.length
      ? data.items
          .map((item) => `${item.created_at}  ${item.status.padEnd(7)}  ${item.action}  ${item.target_id || "-"}  ${item.message}`)
          .join("\n")
      : "暂无日志";
  } catch (error) {
    writeLog(error.message);
  }
}

async function generateNearestDayReports() {
  const nearest = await adminFetch("/api/matches/nearest-day");
  const matches = nearest.items || [];
  if (!matches.length) {
    setProgress(0, 0, "最近赛事日暂无比赛。");
    return { ok: true, scope: "nearest-day", count: 0, items: [] };
  }

  const startedAt = Date.now();
  const generated = [];
  setProgress(0, matches.length, `${nearest.label || "最近赛事日"}：准备生成 ${matches.length} 场比赛。`);
  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index];
    const label = `${match.home} vs ${match.away}`;
    setProgress(index, matches.length, `正在生成第 ${index + 1} 场：${label}`);
    writeLog(`正在生成第 ${index + 1}/${matches.length} 场：${label}\n已完成：${generated.length} 场`);
    const matchStartedAt = Date.now();
    const timer = setInterval(() => {
      const seconds = Math.floor((Date.now() - matchStartedAt) / 1000);
      const softProgress = index + Math.min(0.85, seconds / 55);
      setProgress(softProgress, matches.length, `正在生成第 ${index + 1} 场：${label}，已等待 ${seconds} 秒。`, `${index} / ${matches.length}`);
    }, 1000);
    let result;
    try {
      result = await adminFetch(`/api/admin/matches/${match.id}/generate?publish=true&reasoning_effort=high&thinking=enabled`, { method: "POST" });
    } finally {
      clearInterval(timer);
    }
    const seconds = ((Date.now() - matchStartedAt) / 1000).toFixed(1);
    generated.push({ matchId: match.id, label, seconds, reportId: result.report_id, status: result.status });
    setProgress(index + 1, matches.length, `已完成：${label}，耗时 ${seconds} 秒。`);
  }

  return {
    ok: true,
    scope: "nearest-day",
    label: nearest.label,
    count: generated.length,
    seconds: Number(((Date.now() - startedAt) / 1000).toFixed(1)),
    items: generated,
  };
}

async function generateChampionPrediction() {
  const startedAt = Date.now();
  setProgress(0.08, 1, "正在生成冠军预测，DeepSeek 正在写各队争冠分析。", "0 / 1");
  const timer = setInterval(() => {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    const softProgress = Math.min(0.9, 0.08 + seconds / 45);
    setProgress(softProgress, 1, `正在生成冠军预测，已等待 ${seconds} 秒。`, "0 / 1");
  }, 1000);
  try {
    const result = await adminFetch("/api/admin/tournament/generate-champion-prediction?publish=true&reasoning_effort=high&thinking=enabled", { method: "POST" });
    const seconds = ((Date.now() - startedAt) / 1000).toFixed(1);
    setProgress(1, 1, `冠军预测生成完成，耗时 ${seconds} 秒。`, "1 / 1");
    return { ...result, seconds: Number(seconds) };
  } finally {
    clearInterval(timer);
  }
}

document.querySelector("#saveToken").addEventListener("click", () => {
  adminState.token = tokenInput.value.trim();
  localStorage.setItem("wc-admin-token", adminState.token);
  writeLog("Token 已保存");
});

adminLoginButton.addEventListener("click", async () => {
  setBusy(adminLoginButton, true, "验证中...");
  adminLoginMessage.textContent = "正在验证进入密码...";
  try {
    await publicFetch("/api/admin/page-login", {
      method: "POST",
      body: JSON.stringify({ password: adminPassword.value }),
    });
    adminPassword.value = "";
    showAdminShell();
    await loadAdminDashboard();
  } catch (error) {
    showAdminLogin(error.message);
  } finally {
    setBusy(adminLoginButton, false);
  }
});

adminPassword.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    adminLoginButton.click();
  }
});

adminShell.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (
    !button ||
    button.dataset.runJob ||
    button.dataset.research ||
    button.dataset.generate ||
    button.dataset.wechatPreview ||
    button.dataset.wechatPush ||
    button.id === "generateWechatDaily" ||
    button.id === "refreshWechatArticles" ||
    button.id === "pushWechatDraft"
  )
    return;
  setBusy(button, true);
  writeLog(`${button.dataset.originalText || button.textContent}处理中，请稍候...`);
  try {
    if (button.dataset.action === "sync-fixtures") writeLog(await adminFetch("/api/admin/sync/fixtures", { method: "POST" }));
    if (button.dataset.action === "sync-odds") writeLog(await adminFetch("/api/admin/sync/odds", { method: "POST" }));
    if (button.dataset.action === "nearest-day") writeLog(await generateNearestDayReports());
    if (button.dataset.action === "champion") writeLog(await generateChampionPrediction());
    if (button.dataset.action === "refresh") {
      await loadAdminDashboard();
    }
    if (button.dataset.action === "refresh-status") {
      await loadDataStatus();
    }
    if (button.dataset.action === "refresh-jobs") {
      await loadJobs();
    }
    if (button.dataset.action === "nearest-day" || button.dataset.action === "champion") {
      await loadMatches();
      await loadDataStatus();
      await loadJobs();
    }
  } catch (error) {
    writeLog(error.message);
  } finally {
    setBusy(button, false);
  }
});

document.querySelector("#jobList").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-run-job]");
  if (!button) return;
  const jobId = button.dataset.runJob;
  setBusy(button, true);
  writeLog(`正在运行任务：${jobId}`);
  try {
    const result = await adminFetch(`/api/admin/jobs/${jobId}/run`, { method: "POST" });
    writeLog(result);
    await loadJobs();
    await loadDataStatus();
    await loadMatches();
  } catch (error) {
    writeLog(error.message);
  } finally {
    setBusy(button, false);
  }
});

document.querySelector("#jobList").addEventListener("submit", async (event) => {
  const form = event.target.closest("form[data-job-config]");
  if (!form) return;
  event.preventDefault();
  const button = form.querySelector("button[data-save-job]");
  const jobId = form.dataset.jobConfig;
  setBusy(button, true, "保存中...");
  try {
    const result = await adminFetch(`/api/admin/jobs/${jobId}/config`, {
      method: "PUT",
      body: JSON.stringify(readJobConfig(form)),
    });
    writeLog(result);
    await loadJobs();
  } catch (error) {
    writeLog(error.message);
  } finally {
    setBusy(button, false);
  }
});

document.querySelector("#adminMatches").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const researchId = button.dataset.research;
  const generateId = button.dataset.generate;
  setBusy(button, true);
  writeLog(`${button.dataset.originalText || button.textContent}处理中，请稍候...`);
  try {
    if (researchId) writeLog(await adminFetch(`/api/admin/matches/${researchId}/research`, { method: "POST" }));
    if (generateId) writeLog(await adminFetch(`/api/admin/matches/${generateId}/generate?publish=true`, { method: "POST" }));
    await loadMatches();
    await loadLogs();
  } catch (error) {
    writeLog(error.message);
  } finally {
    setBusy(button, false);
  }
});

refreshWechatArticles.addEventListener("click", async () => {
  setBusy(refreshWechatArticles, true);
  try {
    await loadWechatArticles();
    writeLog("公众号文章列表已刷新");
  } catch (error) {
    writeLog(error.message);
  } finally {
    setBusy(refreshWechatArticles, false);
  }
});

generateWechatDaily.addEventListener("click", async () => {
  setBusy(generateWechatDaily, true, "生成中...");
  writeLog("正在生成公众号每日前瞻...");
  try {
    const result = await generateWechatDailyPreview();
    writeLog(result);
    await loadLogs();
    await loadDataStatus();
  } catch (error) {
    writeLog(error.message);
  } finally {
    setBusy(generateWechatDaily, false);
  }
});

pushWechatDraft.addEventListener("click", async () => {
  setBusy(pushWechatDraft, true, "推送中...");
  writeLog("正在推送公众号草稿箱...");
  try {
    const result = await pushSelectedWechatDraft();
    writeLog(result);
    await loadLogs();
  } catch (error) {
    writeLog(error.message);
  } finally {
    setBusy(pushWechatDraft, false);
  }
});

wechatArticleList.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  const previewId = button.dataset.wechatPreview;
  const pushId = button.dataset.wechatPush;
  setBusy(button, true);
  try {
    if (previewId) {
      const article = await loadWechatArticleDetail(previewId);
      writeLog(article);
    }
    if (pushId) {
      const result = await pushSelectedWechatDraft(pushId);
      writeLog(result);
    }
  } catch (error) {
    writeLog(error.message);
  } finally {
    setBusy(button, false);
  }
});

checkAdminPageSession();
