"""
AnySender Web 控制台 —— Flask API

启动后在 127.0.0.1:8765 提供本地网页界面：
  - 任务列表 / 增删改 / 立即执行（含试运行）
  - 调度器状态 / 插件状态 / 下次运行时间
  - 实时日志（SSE，带 seq 断线续传）
  - 最近运行台账
"""

import json
import logging
import os
import time

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

# 关闭 Flask/Werkzeug 开发服务器访问日志刷屏（只显示 WARN 及以上）
logging.getLogger("werkzeug").setLevel(logging.WARNING)

CONFIG_TASKS = None  # config/tasks.yaml 绝对路径
SYS_PATH = None  # 项目根目录
_scheduler = None
_plugin_manager = None
_event_bus = None
_logger = None
_ledger = None


def _load_tasks_file() -> list:
    """读取用户 config/tasks.yaml 中的 tasks 列表。"""
    if not CONFIG_TASKS or not os.path.isfile(CONFIG_TASKS):
        return []
    import yaml

    with open(CONFIG_TASKS, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    tasks = data.get("tasks", [])
    return tasks if isinstance(tasks, list) else []


def _save_tasks_file(tasks: list) -> None:
    import yaml

    with open(CONFIG_TASKS, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"tasks": tasks},
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


def _clean_task(body: dict) -> dict:
    """只保留任务认识的字段，避免把任意 JSON 写进 tasks.yaml。"""
    allowed = [
        "name",
        "plugin",
        "enabled",
        "schedule",
        "group_name",
        "message",
        "images",
        "plugin_config",
        "dry_run",
    ]
    task = {key: body[key] for key in allowed if key in body}
    if "images" in task:
        images = task.get("images") or []
        if isinstance(images, str):
            images = [images]
        task["images"] = [str(p) for p in images if str(p).strip()]
    if "dry_run" in task:
        task["dry_run"] = bool(task["dry_run"])
    if "enabled" in task:
        task["enabled"] = bool(task["enabled"])
    return task


app = Flask(__name__)


@app.errorhandler(Exception)
def _handle_exception(exc):
    # 404/405 等是正常 HTTP 语义，不能记成“页面异常”再返回 500。
    if isinstance(exc, HTTPException):
        if request.path.startswith("/api/"):
            return jsonify({"error": exc.description, "code": exc.code}), exc.code
        return exc
    if request.path.startswith("/api/"):
        return jsonify({"error": str(exc)}), 500
    logging.getLogger("AnySender").exception("Web 页面异常")
    return "Internal Server Error", 500


def _reload_jobs() -> list:
    if _scheduler is None:
        return []
    try:
        return _scheduler.reload_tasks()
    except Exception as exc:
        logging.getLogger("AnySender").error(f"重新注册任务失败: {exc}")
        return [str(exc)]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return "", 204


@app.route("/api/status")
def api_status():
    next_runs = {}
    if _scheduler:
        for job in _scheduler._scheduler.get_jobs():
            if job.id.startswith("task_"):
                nr = getattr(job, "next_run_time", None)
                next_runs[job.id[5:]] = nr.isoformat() if nr else None
    return jsonify(
        {
            "job_count": _scheduler.job_count() if _scheduler else 0,
            "running": _scheduler.running_count() if _scheduler else 0,
            "next_run": _scheduler.next_run() if _scheduler else None,
            "next_runs": next_runs,
            "plugins": _plugin_manager.loaded_names() if _plugin_manager else [],
            "discovered": _plugin_manager.discovered_names() if _plugin_manager else [],
            "dry_run": os.environ.get("ANYSENDER_DRY_RUN") in ("1", "true", "yes"),
        }
    )


@app.route("/api/tasks")
def api_tasks():
    return jsonify(_load_tasks_file())


@app.route("/api/tasks", methods=["POST"])
def api_tasks_create():
    body = _clean_task(request.get_json(force=True, silent=True) or {})
    if not body.get("name"):
        return jsonify({"error": "任务名不能为空"}), 400
    if not body.get("plugin"):
        return jsonify({"error": "plugin 不能为空"}), 400
    tasks = _load_tasks_file()
    for t in tasks:
        if t.get("name") == body["name"]:
            return jsonify({"error": f"任务名 {body['name']} 已存在"}), 400
    tasks.append(body)
    _save_tasks_file(tasks)
    warnings = _reload_jobs()
    return jsonify({"ok": True, "task": body, "warnings": warnings})


@app.route("/api/tasks/<name>", methods=["PUT"])
def api_tasks_update(name):
    body = _clean_task(request.get_json(force=True, silent=True) or {})
    if not body.get("name"):
        body["name"] = name
    tasks = _load_tasks_file()
    for i, t in enumerate(tasks):
        if t.get("name") == name:
            tasks[i] = body
            _save_tasks_file(tasks)
            warnings = _reload_jobs()
            return jsonify({"ok": True, "task": body, "warnings": warnings})
    return jsonify({"error": f"任务 {name} 不存在"}), 404


@app.route("/api/tasks/<name>", methods=["DELETE"])
def api_tasks_delete(name):
    tasks = _load_tasks_file()
    kept = [t for t in tasks if t.get("name") != name]
    if len(kept) == len(tasks):
        return jsonify({"error": f"任务 {name} 不存在"}), 404
    _save_tasks_file(kept)
    warnings = _reload_jobs()
    return jsonify({"ok": True, "warnings": warnings})


@app.route("/api/tasks/<name>/run", methods=["POST"])
def api_tasks_run(name):
    if not _scheduler:
        return jsonify({"error": "调度器未启动"}), 500
    body = request.get_json(force=True, silent=True) or {}
    dry_run = bool(body.get("dry_run")) or request.args.get("dry_run") in (
        "1",
        "true",
        "yes",
    )
    result = _scheduler.run_now(name, dry_run=dry_run)
    if not result.get("ok"):
        return jsonify({"error": result.get("error", "执行失败")}), result.get(
            "status", 400
        )
    return jsonify(result), 202


@app.route("/api/runs")
def api_runs():
    limit = request.args.get("limit", default=50, type=int)
    limit = min(max(limit, 1), 500)
    if _ledger is None:
        return jsonify([])
    return jsonify(_ledger.tail(limit))


@app.route("/api/logs/stream")
def api_logs_stream():
    since = request.args.get("since", default=0, type=int) or 0

    def gen():
        last = since
        try:
            if _logger is None:
                yield ': no-logger\n\n'
                return
            # 首连先把最近 100 条补上，保证 1 秒内能看到内容
            backlog = _logger.recent(0, 100) if last == 0 else _logger.recent(last)
            for item in backlog:
                last = item["seq"]
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            last_ping = time.time()
            while True:
                for item in _logger.recent(last):
                    last = item["seq"]
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                if time.time() - last_ping > 10:
                    yield ': ping\n\n'
                    last_ping = time.time()
                time.sleep(0.3)
        except GeneratorExit:
            return

    return Response(
        gen(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/plugins")
def api_plugins():
    if not _plugin_manager:
        return jsonify([])
    return jsonify(_plugin_manager.loaded_names())


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
        import threading
        import webbrowser

        threading.Timer(
            0.5, lambda: webbrowser.open(f"http://{host}:{port}")
        ).start()

    print(f"[Web] 控制台已启动: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


def bind(
    scheduler,
    plugin_manager,
    event_bus,
    logger,
    config_tasks_path,
    sys_path,
    ledger=None,
):
    global _scheduler, _plugin_manager, _event_bus, _logger, CONFIG_TASKS, SYS_PATH
    global _ledger
    _scheduler = scheduler
    _plugin_manager = plugin_manager
    _event_bus = event_bus
    _logger = logger
    _ledger = ledger if ledger is not None else getattr(scheduler, "ledger", None)
    CONFIG_TASKS = config_tasks_path
    SYS_PATH = sys_path
