# AnySender 代码审查报告

> 范围：`E:\QQautoBot\AnySender`（已按要求跳过 `E:\QQautoBot\AnySender - 副本`）
> 方法：全量阅读 38 个 .py + 全部配置/schema/前端；实机导入验证依赖；easyocr 实测回归。
> 日期：2026-10-23

---

## 一、全貌

一个 Python 写的跨平台"窗口自动化发送器"。核心链路是 pyautogui 模拟键鼠操作 GUI，
截图 + 模板相似度校验发送结果。**不注入进程、不改协议**，属于 UI 自动化。

代码规模：约 38 个 py 文件、~2600 行；设计文档 `ARCHITECTURE.md` 519 行。

---

## 二、架构分层

| 层 | 目录 | 关键约束 |
|---|---|---|
| 入口 | `main.py`（112 行） | 只负责装配，不含业务 |
| 核心框架 | `core/` | **禁止 import 任何 GUI 库**（铁律），主程序不认识"QQ" |
| 平台插件 | `plugins/qq` | 唯一已实现的插件 |
| 插件基类 | `plugins/_base` | Win32 剪贴板互斥 |
| 通知 | `notifier/` | windows-toasts，带按钮交互 |
| Web 控制台 | `web/` | Flask + SSE 实时日志，127.0.0.1:8765 |
| 校验框架 | `checks/` | **实际未接入**（见问题 6） |
| 校准工具 | `tools/calibrate.py` | 按 HSV 色相识别标注色块 → 相对坐标 |

组件关系：`ConfigHub`（配置）/ `PluginManager`（插件）/ `EventBus`（pub-sub）/
`Scheduler`（APScheduler）/ `Watchdog`（配置+健康）/ `Logger`（JSON 结构化）/
`Notifier`（toast）。

---

## 三、两条关键链路

### 3.1 调度链路

```
APScheduler cron（6 段：秒 分 时 日 月 周）
  └─ _on_main_trigger
       ├─ notifier.notify_sending()
       └─ ThreadPoolExecutor.submit(_do_work)
            ├─ merged = plugin_cfg ∪ task.plugin_config → task["resolved_config"]
            ├─ plugin.send_with_lock(task)     ← 非阻塞锁，忙则跳过
            │    ├─ warm_up()   → 激活 QQ 窗口
            │    ├─ send()
            │    ├─ validate()  （插件层，QQ 里恒为 True）
            │    └─ cool_down()
            └─ emit task_completed / task_failed / task_skipped
```

预通知：`add_task` 时用 `DateTrigger` 注册两个一次性 job（提前 300s / 提前 30s），
发送完成后再重新预约下一次。二级通知带「立即执行」「推迟 5 分钟」按钮，通过
`notify_run_now` / `notify_postpone` 事件回传 Scheduler。

### 3.2 QQ 发送链路（`plugins/qq/plugin.py:send`）

```
1  activate_qq_window()        枚举窗口 → 三层强制前台（AttachThreadInput / Alt / AllowSetForegroundWindow）
2  Ctrl+F 打开搜索 → 点搜索框 → pyperclip 粘贴群名 → Enter
3  verify_chat_opened()        easyocr 识别聊天标题区，确认进对群
4  失败 → select_search_result()  OCR 搜索结果下拉，模糊匹配(0.6)后点击
5  再失败 → browse_to_group()    点击联系人列表 → Home → 逐屏 OCR → PageDown（最多 10 次）
6  get_input_target()          相对坐标 or 模板匹配，得到输入框坐标
7  paste_images_to_input()     CF_HDROP 写剪贴板 → 点击 → Ctrl+V
8  send_message()              Ctrl+A → Backspace → 逐字输入 → Enter/Ctrl+Enter
9  validate_input_effect()     截取校验区 → HDR 鲁棒相似度 → 低于阈值截图存档
```

---

## 四、配置体系

- **三级深合并**：`presets/`（出厂）→ `config/`（用户）→ 代码 `get_default_config()`
- **Schema 两级查找**（非合并）：`schemas/qq.json` > `schemas/default/qq.json` > 代码兜底
- 任务字段：`name / enabled / plugin / schedule / plugin_config{group_name,message,images}`
- 核心配置：`config/base.yaml` 已把时区改成 `Asia/Hong_Kong`

---

## 五、并发与状态

| 规则 | 实现 | 行为 |
|---|---|---|
| 同插件串行 | `send_with_lock` 非阻塞锁 | 忙 → 跳过，不算失败 |
| 异插件并行 | 线程池（8 worker） | 互不干扰 |
| 同任务不并发 | `max_instances=1` | 上次未完成则跳过 |
| 剪贴板互斥 | `_clipboard_lock` 类级锁 | 跨插件串行 |
| 生命周期 | `PluginLifecycle` 枚举 | idle/warming_up/sending/validating/cooling/error |

---

## 六、发现的问题

### A. 会直接导致功能不可用

**A1. Web 控制台「立即执行」必然 500**
`web/app.py:118` 调用 `_scheduler._execute_task(t)`，但 `Scheduler` 里没有这个方法
（实际入口是 `_on_main_trigger`）。前端 `app.js:60` POST 该接口 → `AttributeError`。

**A2. 改配置不会热重载**
`core/watchdog.py:64` emit `config_changed`，但全局没有任何订阅者
（`grep config_changed` 仅 1 处）。ARCHITECTURE 第 310 行声称 Scheduler 会订阅重载 —— 实际没有。

**A3. 插件校验失败后仍留在注册表**
`core/plugin_manager.py:68-74`：先 `self._plugins[name] = instance`，再
`validate_config()`；校验抛错后插件不会被移除。

**A4. `retryable` 标记无人消费**
Scheduler 只是在事件里透传 `retryable=True`，没有任何重试逻辑。

**A5. 纯文本任务无法实现**
`plugin.py:140` `if not images: return _fail("images 为空", False)`
—— 想只发文字/链接（广告最典型的形式）会被直接拒掉。

### B. 死代码与文档不符

| # | 位置 | 问题 |
|---|---|---|
| B1 | `checks/` 全套 | `CheckLoader`、`image_match/json_schema/window_visible` 无任何地方 import；`validator.py` 重复实现了同一套 SSIM 算法 |
| B2 | `locator.py:90,162` | `get_search_box_target`、`verify_group_chat_opened` 定义后从未调用 |
| B3 | `plugins/qq/config_schema.json` | 与 `schemas/default/qq.json` 完全重复（旧副本） |
| B4 | `ARCHITECTURE.md:485` | 写的是 **PaddleOCR**，代码实际用 **easyocr** |
| B5 | `ARCHITECTURE.md:226` | 写的是 **winotify**，代码实际用 **windows-toasts** |
| B6 | `requirements.txt` | 缺 flask / easyocr / pyperclip / windows-toasts；又误列了 winotify；与 `deps/*.txt` 不一致 |

### C. 健壮性隐患

**C1. 所有路径都是相对 cwd**
`config`/`presets`/`plugins`/`logs` 全用相对路径，`main.py` 不 chdir。
从别的目录启动（或双击 exe 时工作目录不同）会直接读不到配置。

**C2. easyocr 的 DLL 初始化不稳**
实测出现过一次 `OSError [WinError 1114] 动态链接库(DLL)初始化例程失败
... torch\lib\c10.dll`，重试即恢复。这是 torch 2.13+cpu 在 Windows 上的已知偶发问题。

**C3. 时区混用**
`scheduler.py:74` 用 `datetime.now(tz.utc)` 去和本地时区的 `CronTrigger` 求下次触发时间，
跨时区场景下预警时间可能算错。

**C4. 校验模板是硬门槛**
`validation.enabled: true` 且 `template_path` 不存在时，`validate_config` 直接失败
→ 整个 QQ 插件加载失败（不是跳过校验）。

**C5. 失败截图路径未清洗**
用任务名直接建目录，任务名含 `:` `?` `*` 等字符时会抛异常。

### D. 设计上的固有代价

- 必须抢占**前台焦点和键鼠**，运行期间人不能操作电脑（通知文案自己写了"切勿操作键鼠"）
- QQ 9 的窗口标题恒为 `QQ`，所以基于标题的群校验已失效 —— 这也是代码为什么改成 OCR 校验聊天头
- 单实例单 QQ 窗口，多账号需多进程

---

## 七、为什么历史上一直没发出去（日志 + 代码交叉推断）

| 时间 | 日志 | 推断 |
|---|---|---|
| 5/11-5/12 | `搜索群聊失败：未找到「飞鱼的记事本」` | 这是**旧版代码**的报错文案（当前代码里已不存在），说明当时是另一套实现 |
| 5/12 | `搜索+遍历均失败` | 搜索和 OCR 遍历都没命中 —— 大概率是 OCR 模型/区域校准问题 |
| 5/12 | `无法读取校验模板图` | 模板图路径错误或 cv2 无法读取（中文路径，见下） |
| 5/12 | `Unknown argument: show_log` | 旧版启动参数残留 |
| 8/10 | 启动正常，无任务执行 | `test` 任务 `enabled: false`，压根没跑 |

一个容易被忽略的坑：**`cv2.imread` 不支持中文路径**。项目里 `validator._imread_unicode`
已经用 `np.fromfile + imdecode` 绕过了，但我实测 `easyocr.readtext("中文路径.png")`
内部仍是 `cv2.imread` → 直接返回 None → `AttributeError: 'NoneType' object has no attribute 'shape'`。
所以**任何把文件路径传给 easyocr 的写法都会静默失败**，必须传 numpy 数组（当前 `browser.py`
传的是 pyautogui 截图，是对的）。

---

## 八、当前可运行性

| 检查项 | 结果 |
|---|---|
| Python | 3.14.5 |
| 核心依赖 | APScheduler / Flask / PyYAML / jsonschema / pywin32 / opencv 5.0 / Pillow 12.3 ✅ |
| QQ 插件依赖 | pyautogui / skimage / pyperclip / easyocr ✅ |
| easyocr 模型 | 已缓存（`~/.EasyOCR/model`：craft_mlt_25k + zh_sim_g2），加载 4.6s |
| OCR 实测 | 参考截图 47 条文本、1.8s，中文可识别 ✅ |
| 模块导入 | `core` / `notifier` 均可正常导入 ✅ |
| 版本漂移 | requirements 固定 opencv 4.10 / Pillow 10.4，实装 5.0 / 12.3（暂未见不兼容） |

结论：**程序本身能跑起来，卡在"能不能准确定位并进入目标群"**，不在依赖。

---

## 九、修复优先级建议

**P0（不修就没法用）**
1. 修 `web/app.py:118` 的 `_execute_task`
2. 让纯文本任务可行（A5）—— 广告通常只要文字
3. 按当前 QQ 版本重新校准坐标，并用 `--desaturate` 生成新模板

**P1（影响可靠性）**
4. 绝对路径化（C1）
5. 校验模板缺失时降级为"跳过校验"而不是拒绝加载（C4）
6. 订阅 `config_changed` 实现热重载（A2）

**P2（清理）**
7. 删 `checks/` 或把它真正接进校验管线（B1）
8. 统一 `requirements.txt` 与 `deps/*.txt`（B6）
9. 订正 ARCHITECTURE 里 PaddleOCR / winotify 的描述（B4/B5）
