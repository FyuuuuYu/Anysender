/* 任务卡片渲染、执行/试运行提交 */

import { state } from "./store.js";
import {
  $,
  $$,
  api,
  escapeHtml,
  fmtDateTime,
  fmtSeconds,
  cronText,
  taskGroup,
  taskImages,
  toast,
} from "./util.js";

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

export function renderCards() {
  const list = $("#taskList");
  const empty = $("#taskEmpty");
  if (!list || !empty) return;

  if (!state.tasks.length) {
    list.innerHTML = "";
    empty.hidden = false;
    return;
  }
  empty.hidden = true;
  list.innerHTML = state.tasks
    .map((task, index) => {
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
            <span class="badge ${task.enabled ? "on" : "off"}">${
              task.enabled ? "启用" : "停用"
            }</span>
            ${task.dry_run ? '<span class="badge dry">试运行</span>' : ""}
          </div>
          <div class="task-meta">
            <span class="tag" title="插件">${escapeHtml(task.plugin || "—")}</span>
            <span class="tag" title="目标">${
              group ? escapeHtml(group) : "未设置目标"
            }</span>
            <span class="tag mono" title="调度">${escapeHtml(
              cronText(task.schedule)
            )}</span>
            ${images.length ? `<span class="tag">${images.length} 图</span>` : ""}
          </div>
          <div class="task-facts">
            <span>下次 <b>${
              next ? escapeHtml(fmtDateTime(next)) : "未排程"
            }</b>${next ? ` · ${escapeHtml(fmtSeconds(next))}` : ""}</span>
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
    })
    .join("");
}

export async function runTask(task, dryRun, button) {
  const card = button.closest(".task-card");
  const buttons = $$("button", card);
  const previous = button.innerHTML;
  buttons.forEach((item) => (item.disabled = true));
  button.innerHTML = '<span class="spinner"></span> 提交中';
  try {
    const result = await api(
      `/api/tasks/${encodeURIComponent(task.name)}/run`,
      {
        method: "POST",
        body: JSON.stringify({ dry_run: Boolean(dryRun) }),
      }
    );
    toast(
      `${dryRun ? "已提交试运行" : "已提交执行"}：${task.name}${
        result.run_id ? `（${result.run_id}）` : ""
      }`,
      "ok"
    );
    // 延迟刷新由 app.js 统一处理，避免 tasks ↔ dashboard 循环依赖
    window.setTimeout(
      () => window.dispatchEvent(new Event("anysender:refresh")),
      900
    );
  } catch (error) {
    toast(`提交失败：${error.message}`, "err", 5000);
  } finally {
    button.innerHTML = previous;
    buttons.forEach((item) => (item.disabled = false));
  }
}
