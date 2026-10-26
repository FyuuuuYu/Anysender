/* 主题切换（localStorage 持久化） */

import { $ } from "./util.js";

export function applyTheme(theme) {
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
