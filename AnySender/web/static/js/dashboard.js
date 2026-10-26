/* 状态统计与数据加载 */

import { state } from "./store.js";
import { $, api, fmtDateTime, fmtSeconds, toast } from "./util.js";
import { renderCards } from "./tasks.js";

export function setPill(stateName, text) {
  const pill = $("#statusPill");
  if (!pill) return;
  pill.dataset.state = stateName;
  $("#statusText").textContent = text;
}

export function renderStats() {
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
    setPill("ok", `运行中 · ${tasks.length} 个任务`);
  }
}

export async function loadStatus() {
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

export async function loadTasks() {
  try {
    const data = await api("/api/tasks");
    state.tasks = Array.isArray(data) ? data : data.tasks || [];
    renderStats();
    renderCards();
  } catch (error) {
    toast(`任务读取失败：${error.message}`, "err", 5000);
  }
}

export async function loadRuns() {
  try {
    const data = await api("/api/runs?limit=50");
    state.runs = Array.isArray(data) ? data : [];
    renderCards();
  } catch (error) {
    toast(`运行记录读取失败：${error.message}`, "err", 5000);
  }
}

export async function refreshAll() {
  await Promise.all([loadTasks(), loadStatus(), loadRuns()]);
}
