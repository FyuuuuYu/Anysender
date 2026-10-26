/* 任务弹窗、保存/删除与确认框 */

import { state } from "./store.js";
import { $, api, escapeHtml, taskGroup, taskImages, taskMessage, toast } from "./util.js";
import { refreshAll } from "./dashboard.js";

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
    .map(
      (name) =>
        `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`
    )
    .join("");
  select.value = current || "qq";
}

export function setSwitch(input, checked) {
  input.checked = Boolean(checked);
}

export function updateImageHint() {
  const count = $("#f_images")
    .value.split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean).length;
  $("#imageHint").textContent = count
    ? `${count} 张图片 · 将与文本一起发送`
    : "0 张图片 · 纯文本任务可留空";
}

export function openTaskModal(task = null) {
  state.editing = task ? task.name : null;
  $("#modalTitle").textContent = task ? "编辑任务" : "新建任务";
  $("#modalSub").textContent = task
    ? `任务：${task.name}`
    : "配置平台、目标与发送内容";
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

export function closeTaskModal() {
  if (state.busy) return;
  $("#modalMask").hidden = true;
  state.editing = null;
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

export async function saveTask(event) {
  event.preventDefault();
  if (state.busy) return;
  const body = gatherForm();
  if (!body.name) return toast("任务名不能为空", "err");
  if (!body.plugin) return toast("请选择插件", "err");
  if (body.enabled && !body.schedule) {
    return toast(
      "启用定时时必须填写 Cron；仅手动任务请先关闭“启用定时”",
      "err",
      5000
    );
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

let confirmResolver = null;

export function confirmDialog({ title, text, okText = "确认" }) {
  return new Promise((resolve) => {
    if (confirmResolver) confirmResolver(false);
    confirmResolver = resolve;
    $("#confirmTitle").textContent = title;
    $("#confirmText").textContent = text;
    $("#btnConfirmOk").textContent = okText;
    $("#confirmMask").hidden = false;
  });
}

export function settleConfirm(value) {
  $("#confirmMask").hidden = true;
  if (confirmResolver) {
    const resolve = confirmResolver;
    confirmResolver = null;
    resolve(value);
  }
}

export async function deleteTask(task) {
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
