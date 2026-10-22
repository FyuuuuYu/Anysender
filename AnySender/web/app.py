"""
AnySender Web 控制台 —— Flask API

启动后在 127.0.0.1:8765 提供本地网页界面：
  - 任务列表 / 增删改 / 立即执行
  - 调度器状态
  - 实时日志（SSE）
"""

import json
import logging
import os
import time
import threading
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

# 关闭 Flask/Werkzeug 开发服务器访问日志刷屏（只显示 WARN 及以上）
logging.getLogger("werkzeug").setLevel(logging.WARNING)

CONFIG_TASKS = None      # config/tasks.yaml 绝对路径
SYS_PATH = None          # 项目根目录
_scheduler = None
_plugin_manager = None
_event_bus = None
_logger = None


def _load_tasks_file() -> list:
    """读取用户 config/tasks.yaml 中的 tasks 列表。"""
    if not CONFIG_TASKS or not os.path.isfile(CONFIG_TASKS):
        return []
    import yaml
    with open(CONFIG_TASKS, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("tasks", [])


def _save_tasks_file(tasks: list) -> None:
    import yaml
    with open(CONFIG_TASKS, "w", encoding="utf-8") as f:
        yaml.safe_dump({"tasks": tasks}, f, allow_unicode=True,
                       default_flow_style=False, sort_keys=False)


app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    jobs = _scheduler._scheduler.get_jobs() if _scheduler else []
    next_runs = {}
    for j in jobs:
        if j.id.startswith("task_"):
            nr = j.next_run_time
            next_runs[j.id[5:]] = nr.isoformat() if nr else None
    return jsonify({
        "job_count": _scheduler.job_count() if _scheduler else 0,
        "next_runs": next_runs,
        "plugins": _plugin_manager.loaded_names() if _plugin_manager else [],
    })


@app.route("/api/tasks")
def api_tasks():
    return jsonify(_load_tasks_file())


@app.route("/api/tasks", methods=["POST"])
def api_tasks_create():
    body = request.get_json(force=True, silent=True) or {}
    if not body.get("name"):
        return jsonify({"error": "任务名不能为空"}), 400
    tasks = _load_tasks_file()
    for t in tasks:
        if t.get("name") == body["name"]:
            return jsonify({"error": f"任务名 {body['name']} 已存在"}), 400
    tasks.append(body)
    _save_tasks_file(tasks)
    return jsonify({"ok": True})


@app.route("/api/tasks/<name>", methods=["PUT"])
def api_tasks_update(name):
    body = request.get_json(force=True, silent=True) or {}
    tasks = _load_tasks_file()
    for i, t in enumerate(tasks):
        if t.get("name") == name:
            tasks[i] = body
            _save_tasks_file(tasks)
            return jsonify({"ok": True})
    return jsonify({"error": f"任务 {name} 不存在"}), 404


@app.route("/api/tasks/<name>", methods=["DELETE"])
def api_tasks_delete(name):
    tasks = _load_tasks_file()
    kept = [t for t in tasks if t.get("name") != name]
    if len(kept) == len(tasks):
        return jsonify({"error": f"任务 {name} 不存在"}), 404
    _save_tasks_file(kept)
    return jsonify({"ok": True})


@app.route("/api/tasks/<name>/run", methods=["POST"])
def api_tasks_run(name):
    if not _scheduler:
        return jsonify({"error": "调度器未启动"}), 500
    tasks = _load_tasks_file()
    for t in tasks:
        if t.get("name") == name:
            threading.Thread(target=_scheduler._execute_task, args=[t], daemon=True).start()
            return jsonify({"ok": True})
    return jsonify({"error": f"任务 {name} 不存在"}), 404


@app.route("/api/logs/stream")
def api_logs_stream():
    def gen():
        last = len(_logger._ring) if _logger else 0
        while True:
            if _logger:
                ring = _logger._ring
                for i in range(last, len(ring)):
                    yield f"data: {json.dumps(ring[i], ensure_ascii=False)}\n\n"
                last = len(ring)
            time.sleep(0.5)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache"})


@app.route("/api/plugins")
def api_plugins():
    if not _plugin_manager:
        return jsonify([])
    return jsonify(_plugin_manager.discovered_names())


def run(host="127.0.0.1", port=8765, open_browser=True):
    """启动 Web 服务；返回实际绑定的端口。"""
    import socket
    # 端口被占用自动 +1
    while True:
        try:
            s = socket.socket()
            s.bind((host, port))
            s.close()
            break
        except OSError:
            port += 1

    if open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(f"http://{host}:{port}")).start()

    print(f"[Web] 控制台已启动: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


def bind(scheduler, plugin_manager, event_bus, logger, config_tasks_path, sys_path):
    global _scheduler, _plugin_manager, _event_bus, _logger, CONFIG_TASKS, SYS_PATH
    _scheduler = scheduler
    _plugin_manager = plugin_manager
    _event_bus = event_bus
    _logger = logger
    CONFIG_TASKS = config_tasks_path
    SYS_PATH = sys_path
