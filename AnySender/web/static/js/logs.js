/* 实时日志：SSE、过滤、渲染、复制 */

import { MAX_LOG_LINES, state } from "./store.js";
import { $, escapeHtml, fmtClock, toast } from "./util.js";
import { loadStatus } from "./dashboard.js";

const LEVEL_RANK = { DEBUG: 10, INFO: 20, WARN: 30, ERROR: 40 };

export function levelVisible(level) {
  if (state.logFilter === "ALL") return true;
  const threshold = LEVEL_RANK[state.logFilter] || 0;
  return (LEVEL_RANK[level] || 20) >= threshold;
}

function logLineHtml(item) {
  const level = String(item.level || "INFO");
  const time = item.ts ? fmtClock(item.ts) : "--:--:--";
  const message = item.msg ?? item.message ?? "";
  const taskName = item.task || item.task_name || "";
  const task = taskName
    ? `<span class="log-task">[${escapeHtml(taskName)}]</span> `
    : "";
  return `<div class="log-line log-${escapeHtml(level)}" data-copy="${escapeHtml(
    `${time} ${level} ${taskName ? `[${taskName}] ` : ""}${message}`
  )}">
    <span class="log-time">${escapeHtml(time)}</span>
    <span class="log-lv">${escapeHtml(level)}</span>
    <span class="log-msg">${task}${escapeHtml(message)}</span>
  </div>`;
}

export function renderLogs() {
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

export function connectLogs() {
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
