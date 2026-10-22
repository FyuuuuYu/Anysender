# AnySender 架构文档

> 本文档以**当前代码实际行为**为准（修订于 2026-10-23）。
> 修订记录见文末「文档修订记录」。

## 核心铁律（不可触犯）

```
1. core/ 目录下禁止 import 任何 GUI 库
   违禁名单：pyautogui, cv2, pygetwindow, uiautomation,
            selenium, playwright, win32gui, win32clipboard

2. 主程序不知道任何平台的存在（QQ、微信、钉钉...全是透明的）

3. 新增平台 = 新增插件目录 + 实现接口，核心层一行不改

4. 校验规则：
   grep -r "pyautogui\|cv2\|win32" core/ → 零命中 ✅
```

---

## 整体架构

```
                              ┌────────────┐
                              │  main.py   │
                              │ ~110 行    │
                              │  永不改动   │
                              └─────┬──────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
        ▼                           ▼                           ▼
┌───────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   ConfigHub   │     │   PluginManager      │     │     EventBus        │
│   配置中心     │     │   插件管理器          │     │     事件总线         │
│               │     │                     │     │                     │
│ · 预设 → 用户  │     │ · 扫描 plugins/      │     │ · pub/sub 松耦合    │
│   三级合并     │     │ · 加载/卸载插件      │     │ · 线程安全          │
│ · YAML 解析   │     │ · 生命周期管理        │     │ · 异常隔离          │
│ · 按需加载插件 │     │ · 健康检查代理        │     │                     │
│   配置        │     │                     │     │                     │
└───────┬───────┘     └──────────┬──────────┘     └──────────┬──────────┘
        │                        │                           │
        │                        │                           │
        ▼                        ▼                           ▼
┌───────────────────────────────────────────────────────────────────────┐
│                           Scheduler                                   │
│                            调度器                                      │
│                                                                       │
│  · BackgroundScheduler（APScheduler）                                  │
│  · 线程池：max_workers                                                │
│  · 同一 job 不并发（max_instances = 1）                                 │
│  · 错过补执行窗口 60s（misfire_grace_time = 60）                        │
│  · 事件合并（coalesce = True）                                         │
│  · 调用 plugin.send_with_lock() ← 同插件自动串行                        │
│  · 订阅 notify_postpone / notify_run_now → 推迟/立即执行                │
└───────────────────────────────────┬───────────────────────────────────┘
                                    │
                                    │ SenderPlugin 接口
                                    │ （不知道任何平台细节）
            ┌───────────────────────┼───────────────────────┐
            │                       │                       │
            ▼                       ▼                       ▼
      ┌───────────┐          ┌───────────┐          ┌───────────┐
      │    QQ     │          │  WeChat   │          │ DingTalk  │
      │  Plugin   │          │  Plugin   │          │  Plugin   │
      │           │          │  (占位)    │          │  (占位)    │
      │ pyautogui │          │           │          │           │
      │ cv2       │          │           │          │           │
      │ win32gui  │          │           │          │           │
      └───────────┘          └───────────┘          └───────────┘
            │
            │ 共享
            ▼
      ┌─────────────────────────────────────┐
      │        Win32Plugin（基类）            │
      │  · _clipboard_lock（剪切板互斥锁）    │
      │  · 跨 QQ/微信共享                    │
      └─────────────────────────────────────┘


┌───────────────────────────────────────────────────────────────────────┐
│                           Watchdog                                     │
│                           守护进程                                      │
│                                                                       │
│  · 监控 config/ 目录（轮询文件 mtime，2s 间隔）                         │
│  · 配置变更 → 启动 300s 计时器 → emit("config_changed")                │
│    ⚠ 当前无任何订阅者，热重载尚未接通（见「已知限制」）                   │
│  · 定时遍历已加载插件 → health_check()                                  │
│  · 异常 → emit("plugin_health_issue")                                  │
└───────────────────────────────────────────────────────────────────────┘


┌───────────────────────────────────────────────────────────────────────┐
│                           Notifier                                     │
│                         Windows 通知                                    │
│                                                                        │
│  · windows-toasts 系统级 toast 通知                                     │
│  · 预告：任务前 N 秒弹窗 + 按钮交互                                      │
│    → 「立即执行」emit("notify_run_now")                                 │
│    → 「推迟 5 分钟」emit("notify_postpone")                             │
│  · 进行中：「正在发送，切勿操作键鼠」                                     │
│  · 完成/失败：结果通知                                                   │
│                                                                        │
│  不放在 core/ 内，不违反铁律                                            │
└───────────────────────────────────────────────────────────────────────┘


┌───────────────────────────────────────────────────────────────────────┐
│                            Logger                                      │
│                            日志中心                                     │
│                                                                        │
│  · 结构化日志（JSON 行 / 纯文本双模式）                                  │
│  · 订阅事件 → 自动记录                                                  │
│  · 日志轮转（按大小，10MB）                                             │
│  · 级别：DEBUG / INFO / WARN / ERROR                                    │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 目录物理结构

```
AnySender/
├── core/                               # 核心层——永不引入 GUI 库
│   ├── exceptions.py                   # 异常体系
│   ├── event_bus.py                    # 事件总线 (pub/sub)
│   ├── logger.py                       # 结构化日志
│   ├── plugin_interface.py             # SenderPlugin ABC + SendResult
│   │                                   # + send_with_lock() 并发控制
│   ├── config_hub.py                   # 配置中心 (preset/用户/默认 三级合并)
│   ├── plugin_manager.py               # 插件管理器 (discover/load/unload)
│   ├── scheduler.py                    # 任务调度器 (APScheduler + 线程池)
│   ├── watchdog.py                     # 守护进程 (配置监控 + 健康巡检)
│   └── check_loader.py                 # Check 模块发现/加载（当前未被任何代码引用）
│
├── plugins/                            # 插件目录
│   ├── _base/
│   │   ├── win32_plugin.py             # Win32 GUI 插件基类 (_clipboard_lock)
│   │   └── web_plugin.py               # Web 端插件基类（占位）
│   ├── qq/                             # QQ 插件
│   │   ├── plugin.py                   # QQPlugin(SenderPlugin)
│   │   ├── locator.py                  # 窗口枚举/激活、坐标计算、Ctrl+F 搜索
│   │   ├── browser.py                  # easyocr 搜索结果定位 / 列表遍历 / 聊天头校验
│   │   ├── sender.py                   # 文本 + 图片发送
│   │   ├── validator.py                # HDR 鲁棒图像校验
│   │   └── config_schema.json          # 历史副本，实际读取 schemas/default/qq.json
│   ├── wechat/                         # 微信插件（待实现）
│   ├── dingtalk/                       # 钉钉插件（待实现）
│   └── feishu/                         # 飞书插件（待实现）
│
├── custom_plugins/                     # 用户自定义插件（覆盖内置插件）
│   │                                   # 放入插件目录（含 plugin.py）即可
│   │                                   # 例：custom_plugins/telegram/plugin.py
│   │                                   # 空目录时系统回退到内置 plugins/
│
├── checks/                             # 可组合校验单元（框架存在，当前未接入主流程）
│   ├── base.py                         # Check ABC
│   ├── image_match.py                  # HDR 鲁棒图像相似度
│   ├── json_schema.py                  # JSON Schema 校验
│   └── window_visible.py               # 窗口可见性校验
│
├── user_checks/                        # 用户自定义 check（同名覆盖内置）
│
├── schemas/                            # 插件配置 JSON Schema 目录
│   ├── default/                        # 内置默认 schema（不动）
│   │   └── qq.json
│   └── qq.json                         # 用户自定义 schema（可选，覆盖 default）
│
├── notifier/                           # 通知模块（不在 core/ 内）
│   ├── base.py                         # AbstractNotifier
│   └── win32_toast.py                  # Win32ToastNotifier (windows-toasts)
│
├── deps/                               # 前置依赖管理
│   ├── core.txt                        # 核心依赖
│   ├── qq.txt                          # QQ 插件依赖
│   ├── notify.txt                      # 通知依赖
│   └── setup.py                        # 自动检测 & 安装
│
├── config/                             # 用户配置
│   ├── base.yaml                       # 核心配置覆盖
│   ├── tasks.yaml                      # 任务列表
│   └── plugins/
│       ├── qq.yaml                     # QQ 插件配置
│       └── wechat.yaml                 # 微信插件配置
│
├── presets/                            # 出厂预设，用户不动
│   ├── base.yaml
│   ├── tasks.yaml
│   └── plugins/
│       └── qq.yaml
│
├── logs/                               # 日志输出
│   ├── anySender.log
│   └── errors.log
│
├── screenshots/                        # 截图存档（插件使用）
│   ├── temp/                           # 临时截图（校验通过自动删除）
│   ├── failed/                         # 失败截图（校验未通过保留）
│   ├── done/                           # 关闭校验时仍存档的截图
│   └── reference/                      # 参考模板图
│
├── tests/                              # 测试目录（目录已建，当前为空）
│   ├── test_core/
│   └── test_plugins/
│
├── web/                                # Web 控制台（Flask，127.0.0.1:8765）
│   ├── app.py                          # API + SSE 日志流
│   ├── templates/index.html
│   └── static/{app.js, style.css}
│
├── tools/
│   └── calibrate.py                    # 区域校准工具（HSV 色块 → 相对坐标）
│
├── main.py                             # 入口 ~112 行
├── requirements.txt                    # 全量依赖（开发用，当前与 deps/*.txt 不一致）
├── setup.py                            # 一键安装 / 打包
├── build.bat                           # Windows 一键打包
├── AnySender.spec                      # PyInstaller 配置
└── ARCHITECTURE.md                     # 本文档
```

---

## 模块职责速查

### core/ — 核心框架层

| 文件 | 一句话职责 |
|------|-----------|
| `exceptions.py` | 全项目统一的异常类（PluginLoadError / ConfigValidationError 等） |
| `event_bus.py` | 线程安全的发布/订阅事件总线，各模块通过事件松耦合通信 |
| `logger.py` | 结构化日志（JSON/文本双模式），订阅事件自动记录，按大小轮转 |
| `plugin_interface.py` | `SenderPlugin` 抽象基类，定义所有插件必须实现的方法；`send_with_lock` 提供同插件串行锁 |
| `config_hub.py` | 配置中心：preset → 用户 config → 代码默认值 三级深度合并，YAML 解析 |
| `plugin_manager.py` | 扫描 `custom_plugins/` 和 `plugins/`，加载/卸载插件，代理健康检查 |
| `scheduler.py` | APScheduler + 线程池，注册 cron 定时任务，连接 notifier 做预告/结果通知 |
| `watchdog.py` | 监控 `config/` 目录变更（300s 防抖），定期巡检插件健康状态 |
| `check_loader.py` | 扫描 `checks/` 与 `user_checks/` 动态加载 Check 子类（**当前无调用方**） |

### notifier/ — 系统通知

| 文件 | 一句话职责 |
|------|-----------|
| `base.py` | `AbstractNotifier` 抽象接口（notify / notify_task_soon / notify_sending / notify_done） |
| `win32_toast.py` | Windows toast 通知实现（**windows-toasts**），带"立即执行""推迟5分钟"按钮回调 |

### plugins/_base/ — 插件公共基类

| 文件 | 一句话职责 |
|------|-----------|
| `win32_plugin.py` | 类级别 `_clipboard_lock` 跨插件互斥锁，Windows CF_HDROP 多文件剪切板操作 |
| `web_plugin.py` | Web 端插件基类占位（预留 playwright/selenium） |

### plugins/qq/ — QQ 插件

| 文件 | 一句话职责 |
|------|-----------|
| `plugin.py` | `QQPlugin(SenderPlugin)` 主类，粘合所有子模块，实现完整生命周期 |
| `locator.py` | 窗口枚举/激活（三层强制前台）、坐标换算、Ctrl+F 搜索并进入会话 |
| `browser.py` | **easyocr** 搜索结果定位、会话列表遍历、聊天标题校验 |
| `sender.py` | 将图片写入剪切板并 Ctrl+V 粘贴 + 文本输入 + Enter/Ctrl+Enter 发送 |
| `validator.py` | HDR 鲁棒图像校验：亮度 SSIM + 边缘 SSIM + 直方图相关性 + 截图存档 |
| `config_schema.json` | 早期副本，运行时不会读取（实际读 `schemas/default/qq.json`） |

### deps/ — 依赖管理

| 文件 | 一句话职责 |
|------|-----------|
| `setup.py` | 自动检测 Python 版本/OS/已启用插件 → 按需 pip install，版本不兼容自动回退最新 |
| `core.txt` | 核心依赖：APScheduler, PyYAML, jsonschema, Flask |
| `qq.txt` | QQ 插件依赖：pyautogui, opencv-python, Pillow, pywin32, scikit-image, pyperclip, easyocr |
| `notify.txt` | 通知依赖：windows-toasts |
| `dev.txt` | 开发依赖：pytest, pytest-cov |

### config/ vs presets/ vs schemas/

| 目录 | 用途 | 是否提交 Git |
|------|------|-------------|
| `presets/` | 出厂预设值，用户不修改 | ✅ |
| `config/` | 用户覆盖配置，只写想改的字段 | ✅（注意脱敏） |
| `schemas/default/` | 内置校验规则 | ✅ |
| `schemas/` | 用户自定义校验规则（覆盖 default） | ❌ 可选 |

---

## 配置合并策略

```
presets/base.yaml    ─┐
config/base.yaml     ─┤ → 合并 → 核心配置
                       │
presets/tasks.yaml   ─┐
config/tasks.yaml    ─┤ → 合并 → 任务列表
                       │
presets/plugins/qq.yaml ─┐
config/plugins/qq.yaml  ─┤ → 合并 → QQ 插件配置
                       │
schemas/default/qq.json ─┐
schemas/qq.json         ─┤ → 按优先级查找（不深合并）
```

规则：
- **config**：Deep Merge，用户覆盖 preset，preset 覆盖代码默认值。用户只写想改的字段。
- **schemas**：优先级查找（非合并），`schemas/<name>.json` > `schemas/default/<name>.json` > 代码 `get_default_config()`

---

## 并发控制

```
┌──────────────────┬──────────────────┬──────────────────┐
│      规则        │     实现位置      │      行为         │
├──────────────────┼──────────────────┼──────────────────┤
│ 同插件串行        │ send_with_lock() │ 非阻塞锁，忙→跳过 │
│ 异插件并行        │ 线程池           │ 互不干扰          │
│ 同任务不并发      │ max_instances=1  │ 上次未完成→跳过   │
│ 剪切板互斥        │ _clipboard_lock  │ 跨插件串行        │
│ 失败可重试标记    │ SendResult       │ 仅透传，无重试器  │
└──────────────────┴──────────────────┴──────────────────┘
```

---

## 事件总线

```
┌──────────────────────┬─────────────────┬──────────────────────────────┐
│       事件名          │     发布者       │           订阅者              │
├──────────────────────┼─────────────────┼──────────────────────────────┤
│ config_changed       │ Watchdog        │ ⚠ 无订阅者（热重载未接通）     │
│ task_completed       │ Scheduler       │ Logger (记录成功)             │
│ task_failed          │ Scheduler       │ Logger (记录失败)             │
│ task_skipped         │ Scheduler       │ Logger (记录跳过)             │
│ plugin_health_issue  │ Watchdog        │ Logger (告警)                 │
│ plugin_loaded        │ PluginManager   │ Logger (记录)                 │
│ plugin_unloaded      │ PluginManager   │ Logger (记录)                 │
│ notify_postpone      │ Notifier        │ Scheduler (推迟任务)          │
│ notify_run_now       │ Notifier        │ Scheduler (立即执行)          │
└──────────────────────┴─────────────────┴──────────────────────────────┘
```

---

## 预设配置说明

- **presets/base.yaml** — 调度器参数、日志级别、watchdog 间隔等全局设定
- **presets/tasks.yaml** — 示例任务模板，`enabled: false` 不激活
- **presets/plugins/qq.yaml** — QQ 插件最佳实践默认值

## 用户配置覆盖

配置文件：`config/tasks.yaml`

```yaml
tasks:
  - name: "早报发送"
    enabled: true
    plugin: "qq"
    schedule: "0 30 8 * * *"     # cron: 秒 分 时 日 月 周
    plugin_config:
      group_name: "工作群"
      message: "今日早报..."
      images:
        - "E:/images/news.png"
```

**字段说明**
| 字段 | 必填 | 说明 |
|------|------|------|
| name | ✅ | 任务名，唯一标识 |
| enabled | ✅ | 是否启用 |
| plugin | ✅ | 目标平台名（如 `qq`） |
| schedule | ✅ | cron 六段表达式 |
| plugin_config.group_name | ✅ | 目标群/联系人名 |
| plugin_config.message | ❌ | 附带文本 |
| plugin_config.images | ✅ | 本地图片绝对路径列表（当前实现下不可为空） |

> ⚠ 当前 `QQPlugin.send()` 在 `images` 为空时直接判失败，因此**纯文本任务无法发送**。

---

## 通知交互

Windows 系统级 toast 通知，两级提醒：

| 时机 | 内容 | 交互 |
|------|------|------|
| 提前 N 分钟 | 「xxx 预计 N 分钟后执行」 | 纯提示 |
| 提前 N 秒 | 「xxx 即将执行，请勿移动鼠标」 | 立即执行 / 推迟 5 分钟 |

配置（`config/base.yaml`）：

```yaml
notify:
  enabled: true       # true=开启 / false=关闭
  early_seconds: 300  # 一级提醒：提前秒数（5 分钟）
  soon_seconds: 30    # 二级提醒：提前秒数
```

> ⚠ **已知限制**：`main.py` 目前把 `notify_enabled=True / early_seconds=300 / soon_seconds=30`
> 硬编码传给 Scheduler，`config/base.yaml` 里的 `notify` 段**尚未被读取**。
> 要关闭通知或改时间，需改 `main.py`。

---

## 插件发现策略

```
启动时 PluginManager.discover() 按以下顺序扫描：

  1. custom_plugins/     — 用户自定义插件（高优先级）
  2. plugins/            — 内置默认插件（低优先级）

同名插件 → custom 覆盖 built-in
```

示例：用户在 `custom_plugins/qq/` 放入自己的 `plugin.py` → 启动时自动加载用户版，忽略 `plugins/qq/`。

---

## 插件配置校验（Schema）

查找优先级（高 → 低）：

```
schemas/<plugin_name>.json          →  用户自定义校验规则
schemas/default/<plugin_name>.json  →  内置默认校验规则
插件代码 get_default_config()       →  代码级兜底
```

用户新增自定义校验：在 `schemas/` 下放入 `my_plugin.json` 即可。无需修改任何代码。

> ⚠ 当 `validation.enabled: true` 而 `validation.template_path` 不存在时，
> `validate_config()` 返回失败 → **整个插件加载失败**（不是跳过校验）。

---

## 扩展指南

### 方式一：覆盖内置插件（不改源码）
```bash
# 1. 复制内置插件到 custom_plugins/
cp -r plugins/qq custom_plugins/qq
# 2. 修改 custom_plugins/qq/ 下的代码
# 3. 启动 → 自动加载你的版本
```

### 方式二：新增一个平台（如 Telegram）
```bash
# 1. 创建插件目录
mkdir -p plugins/telegram
# 2. 实现 plugin.py（继承 SenderPlugin）
# 3. 创建 schema（可选）
#    schemas/default/telegram.json
# 4. 在 presets/plugins/ 和 config/plugins/ 下加 telegram.yaml
# 5. 在 deps/ 下加 telegram.txt 依赖
# 6. 启动 → 自动发现
```

### 方式三：通过 custom_plugins/ 新增（不改内置目录）
```bash
# 1. 直接在 custom_plugins/ 下创建目录
mkdir -p custom_plugins/telegram
# 2. 写入 plugin.py（继承 SenderPlugin）
# 3. 启动 → 自动发现 "telegram"
```

core/ 一行不改。

---

## 区域校准（提高定位精度）

插件中的搜索框、输入框、校验区坐标默认是手工填入的相对值。使用校准工具从标注截图自动提取精确位置：

```bash
# 1. 截一张目标窗口（QQ/微信等）的完整截图
# 2. 用任意画图工具在图上画矩形框，颜色对应：
#    红色  → 搜索框区域
#    绿色  → 输入框光标位置
#    蓝色  → 发送后校验区域
#    黄色  → 聊天标题区域（搜索验证用）
#    紫色  → 联系人列表区域
# 3. 保存为 PNG
python tools/calibrate.py 标注图.png --plugin qq
```

脚本自动识别四种色块的包围盒 → 算相对坐标 → 写入 `config/plugins/<plugin>.yaml`。

| 色块 | HSV 色相范围（OpenCV H: 0-180） | 写入字段 |
|------|------|------|
| 红 | 0°-15° / 165°-180° | `search_box_target` |
| 绿 | 45°-80° | `input_target` |
| 蓝 | 95°-130° | `validation_region` |
| 黄 | 22°-38° | `chat_header` |
| 紫 | 130°-170° | `contact_list` |

用 HSV 色相匹配，不看精确 RGB 值——你涂偏红、暗红、亮红都能识别。
截图里 UI 自身颜色干扰大时，加 `--desaturate` 先转灰度再识别。

---

## 搜索模式

QQ 插件支持两种寻找群聊的方式，通过 `config/plugins/qq.yaml` 中的 `search_mode` 切换：

### search（默认）—— 精确搜索
```
Ctrl+F → 点击搜索框 → pyperclip 粘贴群名 → Enter
  → easyocr 识别「聊天标题区」，确认已进入目标群
  → 未进入：OCR 搜索结果下拉，模糊匹配(0.6)后点击
  → 仍未进入：自动回退 browse（需已校准 contact_list）
```

### browse —— 列表遍历
```
点击列表区 → Home 到顶 → 截屏 → easyocr 识文字 → 模糊匹配 → 点击
没找到 → PageDown → 继续（默认最多 10 次，由 max_scrolls 控制）
```
需校准 `contact_list` 区域。

### 群名校验

当前生效的是 `browser.verify_chat_opened()`：对聊天标题区截图 OCR，
再用 `difflib.SequenceMatcher` 与目标群名比对（默认阈值 0.5）。

`locator.verify_group_chat_opened()` 是早期基于**窗口标题**的实现，**已不再被调用**——
QQ 9 的窗口标题恒为 `QQ`，不包含群名，该方案失效。

### OCR 模型

列表遍历 & 搜索验证使用 **easyocr**：

| 指标 | 数值 |
|------|------|
| 框架 | PyTorch（torch 2.13.0+cpu） |
| 模型下载 | craft_mlt_25k.pth + zh_sim_g2.pth，首次自动下载至 `~/.EasyOCR/model` |
| 加载耗时 | 实测约 4.6s（模型已缓存） |
| 识别速度 | 实测 958×585 截图 1.8s / 47 条 |
| 中文识别 | 可用 |

> ⚠ **中文路径陷阱**：`easyocr.readtext(路径)` 内部使用 `cv2.imread`，**不支持中文路径**，
> 会返回 `None` 并抛 `AttributeError: 'NoneType' object has no attribute 'shape'`。
> 项目内 `validator._imread_unicode()` 已用 `np.fromfile + cv2.imdecode` 规避。
> 传参时务必传 **numpy 数组**（如 pyautogui 截图），不要传文件路径。

---

## 已知限制

| # | 限制 | 说明 |
|---|---|---|
| 1 | Web 控制台「立即执行」不可用 | `web/app.py` 调用不存在的 `Scheduler._execute_task()`，会 500 |
| 2 | 配置热重载未接通 | `config_changed` 事件无订阅者 |
| 3 | 纯文本任务不可发 | `images` 为空直接判失败 |
| 4 | `retryable` 无消费者 | 失败任务不会自动重试 |
| 5 | 必须独占键鼠 | 发送期间前台焦点被抢，用户不能操作电脑 |
| 6 | 相对路径依赖工作目录 | 需在项目根目录启动，否则读不到 config/presets |
| 7 | 插件校验失败仍驻留 | `plugin_manager.load()` 先注册后校验 |
| 8 | easyocr DLL 偶发失败 | torch c10.dll 可能抛 WinError 1114，重试可恢复 |

---

## 文档修订记录

**2026-10-23 修订**（与代码对齐）：

| 位置 | 原文 | 改为 |
|---|---|---|
| 架构图 Notifier | winotify | windows-toasts |
| 模块表 `win32_toast.py` | （winotify） | （windows-toasts） |
| 目录树 `core/` | 缺 `check_loader.py` | 已补，并标注无调用方 |
| 目录树 `plugins/qq/` | 缺 `browser.py` | 已补 |
| 目录树 | 列出 `README.md` | 该文件实际不存在，已移除 |
| 目录树 | `main.py` ~60 行 | 实际 112 行 |
| 目录树 | 缺 `web/`、`tools/`、`checks/`、`user_checks/` | 已补 |
| `deps/*.txt` 说明 | core 缺 Flask；qq 缺 pyperclip/easyocr；notify 写 winotify | 已按实际内容更正 |
| 事件总线表 | `config_changed` 订阅者写 Scheduler | 实际无订阅者，已标注 |
| 搜索模式 | 「Ctrl+F → 校验窗口标题」 | 实际是 OCR 校验聊天标题区 |
| 搜索模式 | PaddleOCR | easyocr；补 easyocr 中文路径陷阱 |
| 搜索模式 | browse「最多30次」 | 实际 `max_scrolls=10` |
| 搜索模式 | 称 `verify_group_chat_opened` 生效 | 实际已废弃，生效的是 `browser.verify_chat_opened` |
| 通知交互 | 称可通过 `config/base.yaml` 配置 | 实际 main.py 硬编码，已标注 |
| 通知交互 | 文末重复了一整节 | 已合并为一节 |
| 校准色相 | 紫 140°-165° | 实际 130°-170° |
| 全文 | 无「已知限制」章 | 新增，汇总 8 条 |
