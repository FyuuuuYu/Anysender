/* AnySender 控制台 —— 无构建、无第三方依赖 */

"use strict";

const LEVEL_RANK = { DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40 };
const MAX_LOG_LINES = 400;
const state = {
  tasks: [],
  status: null,
  runs: [],
  logs: [],
  logSeq: 0,
  logFilter: "ALL",
  autoScroll: true,
  editing: null,
  busy: false,
  eventSource: null,
  statusError: false,
  lastStreamErrorAt: 0,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

/* ── 工具 ── */

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { error: text.slice(0, 200) };
    }
  }
  if (!response.ok) {
    const message =
      (payload && (payload.error || payload.message)) ||
      `请求失败（HTTP ${response.status}）`;
    throw new Error(message);
  }
  return payload;
}

function toast(message, kind = "ok", timeout = 3400) {
  const wrap = $("#toasts");
  if (!wrap) return;
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = String(message);
  wrap.appendChild(node);
  while (wrap.children.length > 4) wrap.firstElementChild.remove();
  window.setTimeout(() => {
    node.style.opacity = "0";
    node.style.transition = "opacity .2s";
    window.setTimeout(() => node.remove(), 220);
  }, timeout);
}

function fmtClock(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function fmtDateTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const now = new Date();
  if (date.toDateString() === now.toDateString()) return `今天 ${fmtClock(iso)}`;
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (date.toDateString() === tomorrow.toDateString()) return `明天 ${fmtClock(iso)}`;
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate()
  ).padStart(2, "0")} ${fmtClock(iso)}`;
}

function fmtSeconds(iso) {
  if (!iso) return "";
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (!Number.isFinite(seconds)) return "";
  if (seconds <= 0) return "即将运行";
  if (seconds < 60) return `${seconds} 秒后`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟后`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} 小时后`;
  return `${Math.round(seconds / 86400)} 天后`;
}

function taskGroup(task) {
  return task.group_name || (task.plugin_config || {}).group_name || "";
}

function taskMessage(task) {
  return task.message || (task.plugin_config || {}).message || "";
}

function taskImages(task) {
  const value = task.images ?? (task.plugin_config || {}).images ?? [];
  if (Array.isArray(value)) return value.filter(Boolean);
  return value ? [value] : [];
}

function cronText(schedule) {
  const raw = String(schedule || "").trim();
  if (!raw) return "仅手动";
  const parts = raw.split(/\s+/);
  if (parts.length === 6 && parts[0] === "0" && /^\d+$/.test(parts[1]) && /^\d+$/.test(parts[2])) {
    if (parts[3] === "*" && parts[4] === "*" && parts[5] === "*") {
      return `每天 ${parts[2].padStart(2, "0")}:${parts[1].padStart(2, "0")}`;
    }
    if (parts[3] === "*/2" && parts[4] === "*" && parts[5] === "*") return "每 2 小时";
  }
  return raw;
}

function nextRunOf(name) {
  return ((state.status && state.status.next_runs) || {})[name] || null;
}

function latestRunOf(name) {
  for (let i = state.runs.length - 1; i >= 0; i -= 1) {
    const record = state.runs[i] || {};
    const taskName = record.task || record.task_name || "";
    if (taskName === name) return record;
  }
  return null;
}

function runLabel(record) {
  if (record.skipped) return ["跳过", "err"];
  if (record.success && record.dry_run) return ["试运行", "ok"];
  if (record.success) return ["成功", "ok"];
  return ["失败", "err"];
}

/* ── 状态与统计 ── */

function setPill(stateName, text) {
  const pill = $("#statusPill");
  if (!pill) return;
  pill.dataset.state = stateName;
  $("#statusText").textContent = text;
}

function renderStats() {
  const data = state.status || {};
  const tasks = state.tasks;
  const enabled = tasks.filter((task) => task.enabled).length;
  const plugins = data.plugins || [];
  $("#statTotal").textContent = String(tasks.length);
  $("#statEnabled").textContent = String(enabled);
  $("#statPlugins").textContent = plugins.length ? plugins.join(" / ") : "—";
  $("#statPlugins").title = (data.discovered || []).length
    ? `已发现 ${(data.discovered || []).length} 个插件`
    : "暂无已发现插件";
  const next = data.next_run || null;
  $("#statNext").textContent = next ? `${fmtDateTime(next)}` : "—";
  $("#statNext").title = next ? fmtSeconds(next) : "当前没有已启用的调度";

  $("#dryBanner").hidden = !data.dry_run;
  if (state.statusError) {
    setPill("down", "后端离线");
  } else if (data.dry_run) {
    setPill("warn", `试运行模式 · ${tasks.length} 个任务`);
  } else {
    setPill("ok", `${(data.running || 0) > 0 ? "运行中" : "运行中"} · ${tasks.length} 个任务`);
  }
}

async function loadStatus() {
  try {
    state.status = await api("/api/status");
    state.statusError = false;
    renderStats();
    renderCards();
  } catch (error) {
    if (!state.statusError) toast(`状态读取失败：${error.message}`, "err", 5000);
    state.statusError = true;
    renderStats();
  }
}

async function loadTasks() {
  try {
    const data = await api("/api/tasks");
    state.tasks = Array.isArray(data) ? data : data.tasks || [];
    renderStats();
    renderCards();
  } catch (error) {
    toast(`任务读取失败：${error.message}`, "err", 5000);
  }
}

async function loadRuns() {
  try {
    const data = await api("/api/runs?limit=50");
    state.runs = Array.isArray(data) ? data : [];
    renderCards();
  } catch (error) {
    toast(`运行记录读取失败：${error.message}`, "err", 5000);
  }
}

async function refreshAll() {
  await Promise.all([loadTasks(), loadStatus(), loadRuns()]);
}

/* ── 任务卡片 ── */

function renderCards() {
  const list = $("#taskList");
  const empty = $("#taskEmpty");
  if (!list || !empty) return;

  if (!state.tasks.length) {
    list.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  list.innerHTML = state.tasks.map((task, index) => {
    const group = taskGroup(task);
    const images = taskImages(task);
    const next = nextRunOf(task.name);
    const last = latestRunOf(task.name);
    const lastParts = last ? runLabel(last) : null;
    const lastText = last
      ? `<span title="${escapeHtml(last.detail || "")}">上次 <b class="${
          lastParts[1]
        }">${lastParts[0]}</b> · ${escapeHtml(fmtDateTime(last.ts))}${
          last.duration_ms ? ` · ${Math.round(last.duration_ms)}ms` : ""
        }</span>`
      : '<span>上次 <b>从未执行</b></span>';

    return `
      <article class="task-card ${task.enabled ? "" : "is-disabled"}" data-idx="${index}">
        <div class="task-main">
          <div class="task-title">
            <span class="name">${escapeHtml(task.name)}</span>
            <span class="badge ${task.enabled ? "on" : "off"}">${task.enabled ? "启用" : "停用"}</span>
            ${task.dry_run ? '<span class="badge dry">试运行</span>' : ""}
          </div>
          <div class="task-meta">
            <span class="tag" title="插件">${escapeHtml(task.plugin || "—")}</span>
            <span class="tag" title="目标">${group ? escapeHtml(group) : "未设置目标"}</span>
            <span class="tag mono" title="调度">${escapeHtml(cronText(task.schedule))}</span>
            ${images.length ? `<span class="tag">${images.length} 图</span>` : ""}
          </div>
          <div class="task-facts">
            <span>下次 <b>${next ? escapeHtml(fmtDateTime(next)) : "未排程"}</b>${
              next ? ` · ${escapeHtml(fmtSeconds(next))}` : ""
            }</span>
            ${lastText}
          </div>
        </div>
        <div class="task-actions">
          <button class="btn btn-run" data-act="run">▶ 执行</button>
          <button class="btn btn-ghost" data-act="dry" title="只定位窗口，不点击、不发送">试运行</button>
          <button class="btn btn-ghost" data-act="edit">编辑</button>
          <button class="btn btn-ghost btn-danger-text" data-act="delete">删除</button>
        </div>
      </article>`;
  }).join("");
}

async function runTask(task, dryRun, button) {
  const card = button.closest(".task-card");
  const buttons = $$("button", card);
  const previous = button.innerHTML;
  buttons.forEach((item) => (item.disabled = true));
  button.innerHTML = '<span class="spinner"></span> 提交中';
  try {
    const result = await api(`/api/tasks/${encodeURIComponent(task.name)}/run`, {
      method: "POST",
      body: JSON.stringify({ dry_run: Boolean(dryRun) }),
    });
    toast(
      `${dryRun ? "已提交试运行" : "已提交执行"}：${task.name}${
        result.run_id ? `（${result.run_id}）` : ""
      }`,
      "ok"
    );
    window.setTimeout(() => {
      loadRuns().catch(() => {});
      loadStatus().catch(() => {});
    }, 900);
  } catch (error) {
    toast(`提交失败：${error.message}`, "err", 5000);
  } finally {
    button.innerHTML = previous;
    buttons.forEach((item) => (item.disabled = false));
  }
}

/* ── 弹窗 ── */

function fillPluginOptions(current) {
  const select = $("#f_plugin");
  if (!select) return;
  const names = new Set([
    ...((state.status && state.status.plugins) || []),
    ...((state.status && state.status.discovered) || []),
    "qq",
  ]);
  if (current) names.add(current);
  select.innerHTML = Array.from(names)
    .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
    .join("");
  select.value = current || "qq";
}

function setSwitch(input, checked) {
  input.checked = Boolean(checked);
}

function openTaskModal(task = null) {
  state.editing = task ? task.name : null;
  $("#modalTitle").textContent = task ? "编辑任务" : "新建任务";
  $("#modalSub").textContent = task ? `任务：${task.name}` : "配置平台、目标与发送内容";
  $("#f_oldName").value = task ? task.name : "";
  $("#f_name").value = task ? task.name : "";
  fillPluginOptions(task ? task.plugin : "qq");
  $("#f_group").value = task ? taskGroup(task) : "";
  $("#f_message").value = task ? taskMessage(task) : "";
  $("#f_images").value = task ? taskImages(task).join("\n") : "";
  $("#f_schedule").value = (task && task.schedule) || "";
  setSwitch($("#f_enabled"), task ? Boolean(task.enabled) : true);
  setSwitch($("#f_dry_run"), task ? Boolean(task.dry_run) : false);
  updateImageHint();
  $("#modalMask").hidden = false;
  window.setTimeout(() => $("#f_name").focus(), 40);
}

function closeTaskModal() {
  if (state.busy) return;
  $("#modalMask").hidden = true;
  state.editing = null;
}

function updateImageHint() {
  const count = $("#f_images")
    .value.split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean).length;
  $("#imageHint").textContent = count
    ? `${count} 张图片 · 将与文本一起发送`
    : "0 张图片 · 纯文本任务可留空";
}

function gatherForm() {
  return {
    name: $("#f_name").value.trim(),
    plugin: $("#f_plugin").value,
    enabled: $("#f_enabled").checked,
    dry_run: $("#f_dry_run").checked,
    schedule: $("#f_schedule").value.trim(),
    group_name: $("#f_group").value.trim(),
    message: $("#f_message").value,
    images: $("#f_images")
      .value.split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean),
  };
}

async function saveTask(event) {
  event.preventDefault();
  if (state.busy) return;
  const body = gatherForm();
  if (!body.name) return toast("任务名不能为空", "err");
  if (!body.plugin) return toast("请选择插件", "err");
  if (body.enabled && !body.schedule) {
    return toast("启用定时时必须填写 Cron；仅手动任务请先关闭“启用定时”", "err", 5000);
  }
  if (!body.message.trim() && !body.images.length) {
    return toast("文本消息与图片至少填一项", "err");
  }

  state.busy = true;
  const button = $("#btnSave");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "保存中…";
  const oldName = $("#f_oldName").value;
  try {
    const result = await api(
      oldName ? `/api/tasks/${encodeURIComponent(oldName)}` : "/api/tasks",
      { method: oldName ? "PUT" : "POST", body: JSON.stringify(body) }
    );
    $("#modalMask").hidden = true;
    state.editing = null;
    toast(oldName ? `已保存：${body.name}` : `已创建：${body.name}`, "ok");
    const warnings = (result && result.warnings) || [];
    if (warnings.length) toast(warnings.join("；"), "warn", 6000);
    await refreshAll();
  } catch (error) {
    toast(`保存失败：${error.message}`, "err", 6000);
  } finally {
    state.busy = false;
    button.disabled = false;
    button.textContent = original;
  }
}

/* ── 删除确认 ── */

let confirmResolver = null;

function confirmDialog({ title, text, okText = "确认" }) {
  return new Promise((resolve) => {
    if (confirmResolver) confirmResolver(false);
    confirmResolver = resolve;
    $("#confirmTitle").textContent = title;
    $("#confirmText").textContent = text;
    $("#btnConfirmOk").textContent = okText;
    $("#confirmMask").hidden = false;
  });
}

function settleConfirm(value) {
  $("#confirmMask").hidden = true;
  if (confirmResolver) {
    const resolve = confirmResolver;
    confirmResolver = null;
    resolve(value);
  }
}

async function deleteTask(task) {
  const ok = await confirmDialog({
    title: "删除任务",
    text: `确定删除「${task.name}」？该操作会写入 config/tasks.yaml，且不可撤销。`,
    okText: "删除",
  });
  if (!ok) return;
  try {
    const result = await api(`/api/tasks/${encodeURIComponent(task.name)}`, {
      method: "DELETE",
    });
    toast(`已删除：${task.name}`, "ok");
    if (result && result.warnings && result.warnings.length) {
      toast(result.warnings.join("；"), "warn", 6000);
    }
    await refreshAll();
  } catch (error) {
    toast(`删除失败：${error.message}`, "err", 5000);
  }
}

/* ── 日志 ── */

function levelVisible(level) {
  if (state.logFilter === "ALL") return true;
  const threshold = LEVEL_RANK[state.logFilter] || 0;
  return (LEVEL_RANK[level] || 20) >= threshold;
}

function logLineHtml(item) {
  const level = String(item.level || "INFO");
  const time = item.ts ? fmtClock(item.ts) : "--:--:--";
  const message = item.msg ?? item.message ?? "";
  const taskName = item.task || item.task_name || "";
  const task = taskName ? `<span class="log-task">[${escapeHtml(taskName)}]</span> ` : "";
  return `<div class="log-line log-${escapeHtml(level)}" data-copy="${escapeHtml(
    `${time} ${level} ${taskName ? `[${taskName}] ` : ""}${message}`
  )}">
    <span class="log-time">${escapeHtml(time)}</span>
    <span class="log-lv">${escapeHtml(level)}</span>
    <span class="log-msg">${task}${escapeHtml(message)}</span>
  </div>`;
}

function renderLogs() {
  const box = $("#logBox");
  if (!box) return;
  const visible = state.logs.filter((item) => levelVisible(item.level || "INFO"));
  if (!visible.length) {
    box.innerHTML = '<div class="log-empty">暂无日志</div>';
  } else {
    box.innerHTML = visible.map(logLineHtml).join("");
  }
  $("#logCount").textContent = `${state.logs.length} 条 · ${
    state.eventSource ? "SSE 已连接" : "等待连接"
  }`;
  if (state.autoScroll) box.scrollTop = box.scrollHeight;
}

function pushLog(item) {
  if (!item || typeof item !== "object") return;
  if (item.seq && item.seq <= state.logSeq) return;
  if (item.seq) state.logSeq = item.seq;
  state.logs.push(item);
  if (state.logs.length > MAX_LOG_LINES) state.logs.shift();
  const box = $("#logBox");
  if (!box) return;
  if (levelVisible(item.level || "INFO")) {
    const empty = box.querySelector(".log-empty");
    if (empty) empty.remove();
    box.insertAdjacentHTML("beforeend", logLineHtml(item));
    while (box.children.length > MAX_LOG_LINES) box.firstElementChild.remove();
  }
  $("#logCount").textContent = `${state.logs.length} 条 · SSE 已连接`;
  if (state.autoScroll) box.scrollTop = box.scrollHeight;
}

function connectLogs() {
  if (state.eventSource) state.eventSource.close();
  const source = new EventSource(`/api/logs/stream?since=${state.logSeq}`);
  state.eventSource = source;
  source.onmessage = (event) => {
    try {
      pushLog(JSON.parse(event.data));
    } catch {
      /* 忽略半包 */
    }
  };
  source.onopen = () => {
    if (state.statusError) loadStatus().catch(() => {});
    if (!state.logs.length) {
      $("#logCount").textContent = "0 条 · SSE 已连接";
    }
  };
  source.onerror = () => {
    const now = Date.now();
    if (now - state.lastStreamErrorAt > 60000) {
      state.lastStreamErrorAt = now;
      toast("日志流断开，正在自动重连…", "warn");
    }
  };
}

/* ── 主题 ── */

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem("anysender-theme", theme);
  } catch {
    /* 忽略隐私模式限制 */
  }
  $("#themeBtn").textContent = theme === "light" ? "☀️" : "🌙";
  $("#themeBtn").setAttribute(
    "aria-label",
    theme === "light" ? "切换到深色主题" : "切换到浅色主题"
  );
}

/* ── 事件 ── */

function bindEvents() {
  $("#btnNew").addEventListener("click", () => openTaskModal());
  $("#btnEmptyNew").addEventListener("click", () => openTaskModal());
  $("#btnCloseModal").addEventListener("click", closeTaskModal);
  $("#btnCancel").addEventListener("click", closeTaskModal);
  $("#taskForm").addEventListener("submit", saveTask);
  $("#f_images").addEventListener("input", updateImageHint);

  $("#modalMask").addEventListener("mousedown", (event) => {
    if (event.target === $("#modalMask")) closeTaskModal();
  });
  $("#confirmMask").addEventListener("mousedown", (event) => {
    if (event.target === $("#confirmMask")) settleConfirm(false);
  });
  $("#btnConfirmCancel").addEventListener("click", () => settleConfirm(false));
  $("#btnConfirmOk").addEventListener("click", () => settleConfirm(true));

  $("#taskList").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-act]");
    if (!button) return;
    const card = button.closest(".task-card");
    if (!card) return;
    const task = state.tasks[Number(card.dataset.idx)];
    if (!task) return;
    const action = button.dataset.act;
    if (action === "run") runTask(task, false, button);
    if (action === "dry") runTask(task, true, button);
    if (action === "edit") openTaskModal(task);
    if (action === "delete") deleteTask(task);
  });

  $("#statusPill").addEventListener("click", async () => {
    await loadStatus();
    toast("状态已刷新", "ok", 1400);
  });

  $("#themeBtn").addEventListener("click", () => {
    const current = document.documentElement.dataset.theme === "light" ? "light" : "dark";
    applyTheme(current === "light" ? "dark" : "light");
  });

  $("#btnAutoScroll").addEventListener("click", (event) => {
    state.autoScroll = !state.autoScroll;
    event.currentTarget.classList.toggle("is-on", state.autoScroll);
    if (state.autoScroll) {
      const box = $("#logBox");
      box.scrollTop = box.scrollHeight;
    }
  });
  $("#btnClearLog").addEventListener("click", () => {
    state.logs = [];
    state.logSeq = 0;
    $("#logBox").innerHTML = '<div class="log-empty">暂无日志</div>';
    $("#logCount").textContent = "0 条 · 已清屏（服务端环形日志仍在）";
    toast("已清屏（仅前端）", "ok", 2200);
  });
  $("#logFilter").addEventListener("change", (event) => {
    state.logFilter = event.target.value;
    renderLogs();
  });

  $("#logBox").addEventListener("click", (event) => {
    const line = event.target.closest("[data-copy]");
    if (!line) return;
    const text = line.dataset.copy || "";
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        () => toast("已复制该行", "ok", 1600),
        () => toast("复制失败", "err", 2000)
      );
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!$("#confirmMask").hidden) settleConfirm(false);
    else if (!$("#modalMask").hidden) closeTaskModal();
  });
}

/* ── 启动 ── */

async function boot() {
  applyTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  bindEvents();
  await refreshAll();
  connectLogs();
  window.setInterval(() => {
    if (!document.hidden) loadStatus().catch(() => {});
  }, 5000);
  window.setInterval(() => {
    if (!document.hidden) loadRuns().catch(() => {});
  }, 12000);
}

document.addEventListener("DOMContentLoaded", boot);
