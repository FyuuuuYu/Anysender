const $ = (s) => document.querySelector(s);

async function api(url, method = "GET", body = null) {
  const opt = { method };
  if (body) {
    opt.headers = { "Content-Type": "application/json" };
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(url, opt);
  return r.json();
}

/* ── 任务列表 ── */
async function loadTasks() {
  const tasks = await api("/api/tasks");
  const box = $("#taskList");
  if (!tasks.length) {
    box.innerHTML = '<div class="empty-hint">还没有任务，点右上角「新建任务」开始</div>';
    return;
  }
  box.innerHTML = tasks.map((t) => {
    const imgs = (t.plugin_config?.images || []).length;
    return `
    <div class="task-card ${t.enabled === false ? "disabled" : ""}">
      <div class="task-info">
        <div class="name">${esc(t.name)}</div>
        <div class="meta">
          <span class="tag">${esc(t.plugin || "?")}</span>
          <span class="tag">${esc(t.plugin_config?.group_name || "")}</span>
          <span class="tag">${esc(t.schedule || "无")}</span>
          <span class="tag">${imgs} 图</span>
          <span class="tag">${t.enabled === false ? "已停用" : "启用"}</span>
        </div>
      </div>
      <div class="task-actions">
        <button class="btn btn-success act-run" data-name="${escAttr(t.name)}">▶ 执行</button>
        <button class="btn btn-ghost act-edit" data-name="${escAttr(t.name)}">编辑</button>
        <button class="btn btn-danger act-del" data-name="${escAttr(t.name)}">删除</button>
      </div>
    </div>`;
  }).join("");

  // 事件委托：避免内联 onclick 的引号转义问题
  box.querySelectorAll(".act-run").forEach(b =>
    b.onclick = () => runTask(b.dataset.name));
  box.querySelectorAll(".act-edit").forEach(b =>
    b.onclick = () => openModal(tasks.find(t => t.name === b.dataset.name)));
  box.querySelectorAll(".act-del").forEach(b =>
    b.onclick = () => delTask(b.dataset.name));
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function escAttr(s) { return esc(s).replace(/"/g, "&quot;"); }

async function runTask(name) {
  const r = await api(`/api/tasks/${encodeURIComponent(name)}/run`, "POST");
  if (r.error) alert(r.error);
  else appendLog({ level: "INFO", msg: `手动触发任务: ${name}` });
}

async function delTask(name) {
  if (!confirm(`确认删除任务「${name}」？`)) return;
  await api(`/api/tasks/${encodeURIComponent(name)}`, "DELETE");
  loadTasks();
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
  $("#f_group").value = task?.plugin_config?.group_name ?? "";
  $("#f_schedule").value = task?.schedule ?? "";
  $("#f_message").value = task?.plugin_config?.message ?? "";
  $("#f_images").value = (task?.plugin_config?.images || []).join("\n");
  $("#f_enabled").checked = task ? task.enabled !== false : true;
  $("#modalMask").hidden = false;
}
function closeModal() { $("#modalMask").hidden = true; }

$("#taskForm").onsubmit = async (e) => {
  e.preventDefault();
  const oldName = $("#f_oldName").value;
  const body = {
    name: $("#f_name").value.trim(),
    plugin: $("#f_plugin").value,
    enabled: $("#f_enabled").checked,
    schedule: $("#f_schedule").value.trim(),
    plugin_config: {
      group_name: $("#f_group").value.trim(),
      message: $("#f_message").value,
      images: $("#f_images").value.split("\n").map(s => s.trim()).filter(Boolean)
    }
  };
  if (!body.name) return alert("任务名不能为空");
  if (oldName) await api(`/api/tasks/${encodeURIComponent(oldName)}`, "PUT", body);
  else await api("/api/tasks", "POST", body);
  closeModal();
  loadTasks();
};

/* ── 状态 ── */
async function loadStatus() {
  const s = await api("/api/status");
  $("#jobCount").textContent = s.job_count;
}

/* ── 日志 SSE ── */
const logBox = $("#logBox");
let logBuf = [];

function appendLog(l) {
  const cls = l.level || "INFO";
  const div = document.createElement("div");
  div.className = "log-line log-" + cls;
  const ts = l.ts ? l.ts.slice(5, 19).replace("T", " ") : new Date().toLocaleTimeString();
  div.innerHTML = `<span class="log-time">${ts}</span> [${cls}] ${esc(l.msg || l.detail || "")}`;
  logBox.appendChild(div);
  logBox.scrollTop = logBox.scrollHeight;
}

function connectLogStream() {
  const es = new EventSource("/api/logs/stream");
  es.onmessage = (ev) => {
    try { appendLog(JSON.parse(ev.data)); } catch (_) {}
  };
}
connectLogStream();

$("#btnClearLog").onclick = () => { logBox.innerHTML = ""; };

/* ── 定时刷新 ── */
loadTasks();
loadStatus();
setInterval(loadStatus, 5000);
