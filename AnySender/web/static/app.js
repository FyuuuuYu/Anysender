const $ = (s) => document.querySelector(s);

let TASKS = [];
let lastStatusError = "";

async function api(url, method = "GET", body = null) {
  const opt = { method, headers: {} };
  if (body !== null) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch(url, opt);
  } catch (err) {
    throw new Error("无法连接本地服务，请确认 AnySender 仍在运行");
  }
  const text = await r.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch (_) { data = { error: text }; }
  }
  if (!r.ok) {
    throw new Error((data && data.error) || `请求失败 (HTTP ${r.status})`);
  }
  return data;
}

/* ── Toast ── */
function toast(msg, kind = "info") {
  const box = $("#toasts");
  if (!box) { console.log(`[${kind}] ${msg}`); return; }
  const el = document.createElement("div");
  el.className = `toast toast-${kind}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

/* ── 任务列表 ── */
function taskGroup(t) {
  return t.group_name ?? t.plugin_config?.group_name ?? "";
}
function taskMessage(t) {
  return t.message ?? t.plugin_config?.message ?? "";
}
function taskImages(t) {
  return t.images ?? t.plugin_config?.images ?? [];
}

async function loadTasks() {
  const box = $("#taskList");
  try {
    TASKS = await api("/api/tasks");
  } catch (err) {
    box.innerHTML = `<div class="empty-hint">${esc(err.message)}</div>`;
    toast(err.message, "error");
    return;
  }
  if (!TASKS.length) {
    box.innerHTML = '<div class="empty-hint">还没有任务，点右上角「新建任务」开始</div>';
    return;
  }
  box.innerHTML = TASKS.map((t) => {
    const imgs = taskImages(t).length;
    const dry = t.dry_run ? '<span class="tag tag-warn">试运行</span>' : "";
    return `
    <div class="task-card ${t.enabled === false ? "disabled" : ""}">
      <div class="task-info">
        <div class="name">${esc(t.name)}</div>
        <div class="meta">
          <span class="tag">${esc(t.plugin || "?")}</span>
          <span class="tag">${esc(taskGroup(t))}</span>
          <span class="tag">${esc(t.schedule || "无")}</span>
          <span class="tag">${imgs} 图</span>
          <span class="tag">${t.enabled === false ? "已停用" : "启用"}</span>
          ${dry}
        </div>
      </div>
      <div class="task-actions">
        <button class="btn btn-success act-run">▶ 执行</button>
        <button class="btn btn-warn act-dry">试运行</button>
        <button class="btn btn-ghost act-edit">编辑</button>
        <button class="btn btn-danger act-del">删除</button>
      </div>
    </div>`;
  }).join("");

  // 事件委托：避免内联 onclick 的引号转义问题
  box.querySelectorAll(".task-card").forEach((card, idx) => {
    const task = TASKS[idx];
    card.querySelector(".act-run").onclick = (e) =>
      runTask(task.name, false, e.currentTarget);
    card.querySelector(".act-dry").onclick = (e) =>
      runTask(task.name, true, e.currentTarget);
    card.querySelector(".act-edit").onclick = () => openModal(task);
    card.querySelector(".act-del").onclick = () => delTask(task.name);
  });
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

async function runTask(name, dryRun, btn) {
  if (btn) btn.disabled = true;
  try {
    const r = await api(
      `/api/tasks/${encodeURIComponent(name)}/run`,
      "POST",
      { dry_run: !!dryRun }
    );
    toast((dryRun ? "已提交试运行：" : "已提交执行：") + name, "ok");
    appendLog({
      level: "INFO",
      msg: `手动触发 ${name}${dryRun ? "（试运行）" : ""}，run_id=${r.run_id || "-"}`
    });
    setTimeout(loadStatus, 600);
  } catch (err) {
    toast(err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function delTask(name) {
  if (!confirm(`确认删除任务「${name}」？`)) return;
  try {
    await api(`/api/tasks/${encodeURIComponent(name)}`, "DELETE");
    toast(`已删除：${name}`, "ok");
    await loadTasks();
  } catch (err) {
    toast(err.message, "error");
  }
}

/* ── 弹窗 ── */
$("#btnNew").onclick = () => openModal(null);
$("#btnCloseModal").onclick = closeModal;
$("#btnCancel").onclick = closeModal;
$("#modalMask").addEventListener("click", (e) => {
  if (e.target === $("#modalMask")) closeModal();
});

function openModal(task) {
  $("#modalTitle").textContent = task ? "编辑任务" : "新建任务";
  $("#f_oldName").value = task?.name ?? "";
  $("#f_name").value = task?.name ?? "";
  $("#f_plugin").value = task?.plugin ?? "qq";
  $("#f_group").value = taskGroup(task || {});
  $("#f_schedule").value = task?.schedule ?? "";
  $("#f_message").value = taskMessage(task || {});
  $("#f_images").value = taskImages(task || {}).join("\n");
  $("#f_enabled").checked = task ? task.enabled !== false : true;
  $("#modalMask").hidden = false;
}
function closeModal() { $("#modalMask").hidden = true; }

$("#taskForm").onsubmit = async (e) => {
  e.preventDefault();
  const oldName = $("#f_oldName").value;
  const images = $("#f_images").value
    .split("\n").map((s) => s.trim()).filter(Boolean);
  const body = {
    name: $("#f_name").value.trim(),
    plugin: $("#f_plugin").value,
    enabled: $("#f_enabled").checked,
    schedule: $("#f_schedule").value.trim(),
    group_name: $("#f_group").value.trim(),
    message: $("#f_message").value,
    images
  };
  if (!body.name) return toast("任务名不能为空", "error");
  if (!body.message.trim() && !images.length)
    return toast("纯文本或图片至少要填一项", "error");
  if (body.enabled && !body.schedule)
    return toast("启用任务必须填写 Cron；仅手动执行请先取消启用", "error");
  try {
    let r;
    if (oldName) {
      r = await api(`/api/tasks/${encodeURIComponent(oldName)}`, "PUT", body);
      toast(`已保存：${body.name}`, "ok");
    } else {
      r = await api("/api/tasks", "POST", body);
      toast(`已创建：${body.name}`, "ok");
    }
    (r && r.warnings ? r.warnings : []).forEach((w) => toast(w, "warn"));
    closeModal();
    await loadTasks();
    await loadStatus();
  } catch (err) {
    toast(err.message, "error");
  }
};

/* ── 状态 ── */
function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", {
    hour12: false, month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit"
  });
}

function setPill(text, kind) {
  const pill = $("#statusPill");
  if (!pill) return;
  pill.className = "status-pill pill-" + kind;
  $("#statusText").textContent = text;
}

async function loadStatus() {
  try {
    const s = await api("/api/status");
    $("#jobCount").textContent = s.job_count;
    $("#runningCount").textContent = s.running;
    $("#pluginCount").textContent = (s.plugins || []).length;
    $("#nextRun").textContent = fmtTime(s.next_run);
    setPill(s.dry_run ? "试运行模式" : "运行中", s.dry_run ? "warn" : "ok");
    lastStatusError = "";
  } catch (err) {
    setPill("服务异常", "error");
    if (err.message !== lastStatusError) {
      toast(err.message, "error");
      lastStatusError = err.message;
    }
  }
}

/* ── 日志 SSE ── */
const logBox = $("#logBox");

function appendLog(l) {
  const cls = l.level || "INFO";
  const div = document.createElement("div");
  div.className = "log-line log-" + cls;
  const ts = l.ts ? l.ts.slice(5, 19).replace("T", " ") : new Date().toLocaleTimeString();
  const extra = l.task_name ? ` [${l.task_name}]` : "";
  div.innerHTML = `<span class="log-time">${ts}</span> [${cls}]${esc(extra)} ${esc(l.msg || l.detail || "")}`;
  logBox.appendChild(div);
  while (logBox.childElementCount > 500) logBox.removeChild(logBox.firstChild);
  logBox.scrollTop = logBox.scrollHeight;
}

function connectLogStream() {
  const es = new EventSource("/api/logs/stream");
  es.onmessage = (ev) => {
    try { appendLog(JSON.parse(ev.data)); } catch (_) {}
  };
  es.onerror = () => {
    setPill("日志断线，重连中", "warn");
  };
}
connectLogStream();

$("#btnClearLog").onclick = () => { logBox.innerHTML = ""; };

/* ── 定时刷新 ── */
loadTasks();
loadStatus();
setInterval(loadStatus, 5000);
