/* 基础工具：DOM、转义、时间格式、API、toast —— 无第三方依赖 */

export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) =>
  Array.from(root.querySelectorAll(selector));

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export async function api(path, options = {}) {
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

export function toast(message, kind = "ok", timeout = 3400) {
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

export function fmtClock(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function fmtDateTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const now = new Date();
  if (date.toDateString() === now.toDateString()) return `今天 ${fmtClock(iso)}`;
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (date.toDateString() === tomorrow.toDateString()) {
    return `明天 ${fmtClock(iso)}`;
  }
  return `${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate()
  ).padStart(2, "0")} ${fmtClock(iso)}`;
}

export function fmtSeconds(iso) {
  if (!iso) return "";
  const seconds = Math.round((new Date(iso).getTime() - Date.now()) / 1000);
  if (!Number.isFinite(seconds)) return "";
  if (seconds <= 0) return "即将运行";
  if (seconds < 60) return `${seconds} 秒后`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟后`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} 小时后`;
  return `${Math.round(seconds / 86400)} 天后`;
}

export function taskGroup(task) {
  return task.group_name || (task.plugin_config || {}).group_name || "";
}

export function taskMessage(task) {
  return task.message || (task.plugin_config || {}).message || "";
}

export function taskImages(task) {
  const value = task.images ?? (task.plugin_config || {}).images ?? [];
  if (Array.isArray(value)) return value.filter(Boolean);
  return value ? [value] : [];
}

export function cronText(schedule) {
  const raw = String(schedule || "").trim();
  if (!raw) return "仅手动";
  const parts = raw.split(/\s+/);
  if (
    parts.length === 6 &&
    parts[0] === "0" &&
    /^\d+$/.test(parts[1]) &&
    /^\d+$/.test(parts[2])
  ) {
    if (parts[3] === "*" && parts[4] === "*" && parts[5] === "*") {
      return `每天 ${parts[2].padStart(2, "0")}:${parts[1].padStart(2, "0")}`;
    }
    if (parts[3] === "*/2" && parts[4] === "*" && parts[5] === "*") {
      return "每 2 小时";
    }
  }
  return raw;
}
