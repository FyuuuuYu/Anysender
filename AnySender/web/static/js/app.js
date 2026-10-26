/* 控制台入口：事件绑定与启动（模块拆分见 js/ 目录） */

import { state } from "./store.js";
import { $, toast } from "./util.js";
import { applyTheme } from "./theme.js";
import { refreshAll, loadStatus, loadRuns } from "./dashboard.js";
import { runTask } from "./tasks.js";
import {
  openTaskModal,
  closeTaskModal,
  saveTask,
  deleteTask,
  settleConfirm,
  updateImageHint,
} from "./modal.js";
import { connectLogs, renderLogs } from "./logs.js";

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
    const current =
      document.documentElement.dataset.theme === "light" ? "light" : "dark";
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

  window.addEventListener("anysender:refresh", () => {
    refreshAll().catch(() => {});
  });
}

async function boot() {
  applyTheme(
    document.documentElement.dataset.theme === "light" ? "light" : "dark"
  );
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
