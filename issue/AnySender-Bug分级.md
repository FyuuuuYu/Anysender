# AnySender Bug 分级清单

> 目标：`E:\QQautoBot\AnySender`（仓库根 `E:\QQautoBot`，跳过 `AnySender - 副本`）
> 依据：全量源码通读 + 实机依赖验证 + OCR 回归
> 日期：2026-10-23 ｜ 代码版本：`90c4479`

## 分级标准

| 级别 | 含义 | 处理时机 |
|---|---|---|
| **P0** | 功能不可用 / 核心需求直接失效 | 必须修，否则跑不起来 |
| **P1** | 静默失效、可靠性隐患，出问题很难察觉 | 上线前修 |
| **P2** | 一致性、健壮性、可维护性问题 | 迭代中修 |
| **P3** | 改进建议，不影响当前使用 | 有余力再做 |

## 统计

| 级别 | 数量 |
|---|---|
| P0 | 3 |
| P1 | 8 |
| P2 | 7 |
| P3 | 5 |
| **合计** | **23** |

---

## P0 — 阻断级

### P0-1 Web 控制台「立即执行」必崩

- **位置**：`web/app.py:118`
- **现象**：点击任务卡片上的「▶ 执行」，接口返回 500，浏览器控制台报 `AttributeError`
- **根因**：代码调用 `_scheduler._execute_task(t)`，但 `Scheduler` 类中**不存在**该方法（真实入口是 `_on_main_trigger`，且它是通过 APScheduler 回调触发的）
- **修复**：改为调用 `_scheduler._on_main_trigger(t)`，或给 Scheduler 增加一个公开的 `run_now(task_name)` 方法
- **验证**：`curl -X POST http://127.0.0.1:8765/api/tasks/<name>/run` 返回 200；日志出现 `notify_sending` / `task_completed`

### P0-2 纯文本任务无法发送

- **位置**：`plugins/qq/plugin.py:140`
- **现象**：`images` 为空时直接返回失败 `"images 为空"`，文本根本不会发出去
- **影响**：广告/通知这类**只需要文字**的场景完全不可用
- **修复**：把 `images` 改成可选；`paste_images_to_input()` 仅在 `images` 非空时调用；`message` 与 `images` 至少有一个非空即可
- **验证**：配置一个 `images: []` + `message: "test"` 的任务，能收到消息

### P0-3 坐标/模板与当前 QQ 版本不匹配

- **位置**：`config/plugins/qq.yaml`
- **现象**：历史日志持续出现 `搜索+遍历均失败`、`未能进入群聊`
- **根因**：相对坐标是按旧版 QQ 界面校准的；且 `validation.template_path` 指向的参考图是旧界面截图
- **修复**：
  1. 打开 QQ 截图 → 用画图工具按色块标注（红/绿/蓝/黄/紫）
  2. `python tools/calibrate.py 标注图.png --plugin qq --desaturate`
  3. 重新截一张"已发送成功"的聊天区作为校验模板
- **验证**：`search_mode: search` 下能稳定进入目标群

---

## P1 — 严重（静默失效）

### P1-1 配置热重载根本没接通

- **位置**：`core/watchdog.py:64`（emit）、全局无订阅
- **现象**：改了 `config/*.yaml` 后，运行中的程序行为不变
- **根因**：`config_changed` 事件没有任何订阅者；ARCHITECTURE 原文档声称 Scheduler 会订阅并重载，实际没有
- **修复**：`Scheduler.__init__` 里 `event_bus.subscribe("config_changed", self._on_config_changed)`，重载时移除旧 job 并按新配置重建
- **验证**：改 cron 表达式，等 300s 防抖后 `/api/status` 的 `next_runs` 变化

### P1-2 插件校验失败后仍驻留在注册表

- **位置**：`core/plugin_manager.py:68-74`
- **现象**：配置非法时抛 `PluginLoadError`，但插件实例已写入 `self._plugins`
- **影响**：后续 `get(name)` 仍能拿到一个配置非法的实例
- **修复**：把 `validate_config()` 提到注册之前；失败则不写入字典
- **验证**：故意把 `validation.luma_weight` 改成 0.5，启动后 `plugin_manager.loaded_names()` 应为空

### P1-3 `retryable` 标记无人消费

- **位置**：`core/scheduler.py:146-151`
- **现象**：`SendResult.retryable=True` 只是被写进日志，没有任何重试逻辑
- **修复**：在事件回调里加简单的退避重试（如 3 次、间隔 10s/30s/60s），或明确文档化"不重试"

### P1-4 easyocr 中文路径陷阱

- **位置**：`plugins/qq/browser.py`（当前安全）、任何传路径给 OCR 的写法（危险）
- **现象**：
  ```
  [WARN] cv::findDecoder imread_('...\屏幕截图 2026-05-11 182207.png'): can't open/read file
  AttributeError: 'NoneType' object has no attribute 'shape'
  ```
- **根因**：`easyocr.readtext(路径)` 内部使用 `cv2.imread`，不支持非 ASCII 路径
- **现状**：`browser.py` 传的是 pyautogui 截图（numpy 数组），安全；`validator._imread_unicode()` 用 `np.fromfile + imdecode` 也安全
- **修复**：统一约定"只传 numpy 数组"；在 `browser._ocr_region` 入口加断言 `isinstance(img, np.ndarray)`
- **验证**：用中文路径调 `readtext` 必现该错误（已实测复现）

### P1-5 所有路径都是相对 cwd

- **位置**：`main.py:40`（`ConfigHub("config","presets")`）、`main.py:45`（`PluginManager("plugins")`）、`core/logger.py:77`（`log_dir = "logs"`）
- **现象**：从别的目录启动（双击 exe、计划任务、快捷方式工作目录不对）→ 读不到配置、日志写到奇怪的地方
- **修复**：main.py 开头 `os.chdir(os.path.dirname(os.path.abspath(__file__)))`，或全部改成基于 `__file__` 的绝对路径

### P1-6 校验模板缺失导致插件加载失败（应降级）

- **位置**：`plugins/qq/plugin.py:96-100`
- **现象**：`validation.enabled: true` 且 `template_path` 不存在 → `validate_config` 返回 False → **整个插件加载失败**
- **期望**：模板缺失应视为"跳过校验、仅存档截图"，而不是拒绝启动
- **修复**：模板路径无效时自动把 `validation.enabled` 置 False 并打 WARN

### P1-7 时区混用可能算错预通知时间

- **位置**：`core/scheduler.py:74`
- **现象**：用 `datetime.now(tz.utc)` 与本地时区的 `CronTrigger` 求 `get_next_fire_time`
- **影响**：一级/二级提醒可能提前或延后一个时区偏移（`config/base.yaml` 已把时区设为 `Asia/Hong_Kong`）
- **修复**：统一用 tz-aware 的本地时间，或 `trigger.get_next_fire_time(None, datetime.now(ZoneInfo(self._timezone_str)))`

### P1-8 easyocr/torch 偶发 DLL 初始化失败

- **位置**：`plugins/qq/browser.py:22`（`easyocr.Reader(...)` 首次调用）
- **现象**：实测出现过一次
  ```
  OSError [WinError 1114] 动态链接库(DLL)初始化例程失败
  Error loading "...\torch\lib\c10.dll" or one of its dependencies
  ```
  重试即恢复
- **修复**：`_get_reader()` 包一层重试（2~3 次，间隔 1s），失败再降级为"跳过 OCR 走 browse"

---

## P2 — 一般（一致性 / 健壮性）

### P2-1 `checks/` 整套是死代码

- **位置**：`core/check_loader.py`、`checks/*.py`
- **现象**：`CheckLoader` 没有任何调用方；`checks/image_match.py` 与 `plugins/qq/validator.py` 重复实现了同一套 SSIM 算法
- **建议**：要么把 `validator` 改为调用 `ImageMatchCheck`，要么删掉 `checks/` 与 `check_loader.py`

### P2-2 `locator.py` 里两个函数从未被调用

- **位置**：`plugins/qq/locator.py:90`（`get_search_box_target`）、`:162`（`verify_group_chat_opened`）
- **说明**：后者基于窗口标题校验，QQ 9 标题恒为 `QQ`，方案已失效；现在生效的是 `browser.verify_chat_opened`

### P2-3 配置来源不一致

- **位置**：`plugins/qq/plugin.py:130-132`
- **现象**：`group_name` / `message` / `images` 直接从 `task["plugin_config"]` 取，而其他参数走 `task["resolved_config"]`（插件级配置已合并进去）
- **影响**：在 `config/plugins/qq.yaml` 里写默认群名不会生效

### P2-4 失败截图目录未清洗任务名

- **位置**：`plugins/qq/plugin.py:224`
- **现象**：`os.makedirs(failed_dir)` 直接用任务名；任务名含 `:` `?` `*` `/` 会抛异常，掩盖真正的错误

### P2-5 `requirements.txt` 与 `deps/*.txt` 不一致

- **现象**：`requirements.txt` 缺 flask / easyocr / pyperclip / windows-toasts，还误列了 `winotify`（代码实际用 `windows-toasts`）
- **影响**：按 README/requirements 安装会缺包、装错包

### P2-6 前端无错误处理

- **位置**：`web/static/app.js:3-11`
- **现象**：`fetch` 失败或返回非 JSON 时，`r.json()` 直接抛异常，界面无任何提示

### P2-7 测试目录为空

- **位置**：`tests/test_core/`、`tests/test_plugins/`
- **现象**：目录建好了，0 个测试文件；`deps/dev.txt` 里的 pytest 也没被用起来

---

## P3 — 改进建议

### P3-1 无发送台账

建议记录"哪个任务、哪个群、什么时候、成功/失败"，避免重复发送和漏发（对广告场景价值很高）。

### P3-2 无 dry-run / 预览模式

建议加 `--dry-run`：只走到"定位到群 + 填好输入框"就停，不发出去，方便校准坐标。

### P3-3 多账号需多进程

当前单实例单 QQ 窗口，`_force_foreground` 基于窗口标题匹配，多开 QQ 时会命中第一个窗口。

### P3-4 Web 控制台无鉴权

监听 `127.0.0.1:8765`，本机可访问即无口令。本机使用可接受，但别改成 `0.0.0.0`。

### P3-5 启动时会阻塞做依赖检查

`main.py:ensure_deps()` 每次启动都跑 `deps/setup.py --check`，缺包时直接 `pip install`，首次启动可能卡几十秒且依赖网络。

---

## 附：历史失败原因推断

| 时间 | 日志 | 对应问题 |
|---|---|---|
| 5/11–5/12 | `搜索群聊失败：未找到「飞鱼的记事本」` | 旧版实现的报错，当前代码已无此文案 |
| 5/12 | `搜索+遍历均失败` | P0-3 坐标/OCR 定位失效 |
| 5/12 | `无法读取校验模板图` | P1-4 中文路径 / 模板路径问题 |
| 5/12 | `Unknown argument: show_log` | 旧版启动参数残留 |
| 8/10 | 启动正常但无任务执行 | `test` 任务 `enabled: false` |

## 修复顺序建议

```
P0-1（1 行）→ P0-2（改判断）→ P0-3（重新校准，需要人工标注）
   ↓
P1-5（chdir）→ P1-2（顺序）→ P1-6（降级）→ P1-1（订阅）
   ↓
P2-5（依赖清单）→ P2-3（配置来源）→ 其余清理
```

> 参考：完整审查过程见同目录 `AnySender-审查报告.md`。
