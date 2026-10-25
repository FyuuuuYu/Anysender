# AnySender 补充审查意见与 Bug 归档草案

> 范围：`E:\QQautoBot`（重点 `AnySender`；根目录 v1 遗留文件只做清点）
> 依据：全量复读 38 个 py（约 2800 行）、`ARCHITECTURE.md`、全部配置/schema/前端、`issue/` 既有四份文档、git 历史与日志
> 日期：2026-10-26 ｜ 版本：v2（决策回填版）｜ 代码版本：`90c4479`（工作区仅 `issue/` 未入库）
> 定位：**第四份文档，不替代前三份**。做四件事：补漏（3 个 P0、3 个 P1/P2）、纠偏（两处旧结论）、固化通道决策、给出 checks 与 WebUI 两条新增工作流的计划。

---

## 0. 摘要与已拍板决策

### 0.1 已拍板（2026-10-26）

| # | 决策 | 对文档的影响 |
|---|---|---|
| D1 | **QQ 群是硬需求，但项目不能只为 QQ 群而做**；风险不应由账号承担 | 第 4 节重写为「定位 + 通道风险分层」；QQ 降为 Tier C 连接器，核心不托管凭证 |
| D2 | **纯文本是 100% 需求** | P0-2 维持 P0，且列为第一批必交付 |
| D3 | **checks 不删除，接入日志/事件/台账/UI** | P2-1 升为 **P1-11**，第 5 节给出接入设计 |
| D4 | **保留 SSIM**；关键元素检测容易受限，不采用 | P1-9/P0-5 的发送前确认用 SSIM 区域校验实现，第 5.6 节说明边界 |
| D5 | **新增 WebUI 优化计划** | 新增 **P1-12**，第 6 节给出 UI-1～UI-5 分期 |

### 0.2 结论摘要

1. **架构成立，实现未闭环**：当前启动后**加载 0 个插件**、Web「立即执行」必 500、实时日志流**永远为空**——控制台看起来在监控，实际没有任何运行事实。
2. **新增 3 个 P0**：N1 日志死环、N2 插件加载闭环断裂、N3 点击后不复验（**存在发错群风险**）。
3. **新增 2 个 P1/P2 + 1 个 P2**：N4 校准坐标语义、N5 调度语义与健康检查噪音、N6 窗口匹配过宽。
4. **同意复核意见**：dry-run 由 P3 升 P1；「发送前确认」与它并列，两者是同一件事的两面。
5. **通道战略不再二选一**：按 D1 做「分层 + 隔离」，webhook 是 A 类首选但不是 QQ 群的解法；QQ 群的解法只能是 C 类 UI 自动化或 B 类协议端，二选一由账号风险偏好决定，**进程 hook/注入直接排除**。
6. **归档草案规模**：P0 5 项、P1 12 项、P2 9 项、P3 4 项（dry-run 上调；WebUI 为新增工作流），见第 3 节。

---

## 1. 对既有报告的复核结论

### 1.1 可信度

抽查 12 条关键论断，**全部属实**，无夸大、无过时：

| 论断 | 核对结果 |
|---|---|
| `web/app.py:118` 调用不存在的 `_execute_task` | 属实，全项目仅此 1 处调用 |
| `plugin_manager.py:68-74` 先注册后校验 | 属实 |
| `scheduler.py:74` UTC 与本地时区混用 | 属实 |
| `main.py:40/45`、`logger.py:77` 相对路径 | 属实 |
| `plugin.py:140` images 硬门槛 | 属实 |
| `requirements.txt` 误列 winotify | 属实（代码用 `windows-toasts`） |
| `checks/` 全套无调用方 | 属实（`grep CheckLoader` 无业务引用） |
| `locator.py:90/162` 两个函数未被调用 | 属实 |
| `ARCHITECTURE.md` 写 PaddleOCR / winotify | 属实，与实现不符 |
| 5/12、8/10 日志与代码交叉推断 | 结论一致 |
| `90c4479` 后 23 项未修 | 属实，HEAD 未变、工作区干净（除 `issue/`） |
| P3-2 dry-run 应升级 | 同意，且理由成立 |

### 1.2 需要更新的两处

1. **「AnySender - 副本」目录已不存在**：当前根目录只有 `AnySender/`、`build/`、`dist/`、`__pycache__/`、`issue/`。复核意见第 47 条描述的是当时状态，归档时按「已清理」处理，不列为待办。
2. **UI 报告 U3 低估了日志问题**：U3 只指出「清空日志只清 DOM」，实际问题更严重——SSE 流本身从未有数据（见 N1）。

### 1.3 三份报告的共同盲区

- 只审「代码是否按文档实现」，没审「Web 端到底能不能拿到运行事实」；
- 把「插件加载」当成启动即完成，没审「运行期新增任务如何获得插件」；
- 把「点击后不校验」归入「设计固有代价」，没有列为缺陷——对自动化投递，这是最不能接受的一类失败。

---

## 2. 新增问题（N1–N6）

### N1 [P0] 实时日志流永远为空

- **位置**：`core/logger.py:49,62,72`；`web/app.py:126-132`
- **证据**：
  - `Logger.__init__` 在 `core/logger.py:72` 创建 `self._ring`，但全项目**没有任何地方向它 append**；
  - 实际写入的是 `RingHandler` 自己的 `self._ring`（`core/logger.py:49`、`:62`）；
  - Web SSE 读的却是 `_logger._ring`（`web/app.py:129`），永远是空 deque。
- **影响**：控制台「实时日志」面板永远空白；用户无法判断任务是否在跑、是否失败。叠加 N2 与 P0-1，Web 面板事实上是**装饰品**。
- **修复**：让两者共享同一个 deque——`RingHandler` 接收外部 deque，或 `Logger` 在 `_setup_handlers()` 后执行 `self._ring = ring_handler._ring`；同时给 SSE 加 15s 心跳与 `Last-Event-ID`（可选）。
- **验证**：`curl -N http://127.0.0.1:8765/api/logs/stream`，触发任意日志后 1s 内收到 `data: {...}`。

### N2 [P0] 插件加载闭环断裂（Web 新建任务必然执行不了）

- **位置**：`main.py:52-59`；`web/app.py:118`
- **证据**：启动时只对 `enabled: true` 的任务加载插件。当前唯一任务 `enabled: false`，所以启动后**发现 qq、加载 0 个**。通过 Web 新建/启用的任务不会触发任何插件加载；点「执行」时 `_on_main_trigger` 找不到插件，直接 `task_failed: 插件 [qq] 未加载`。
- **影响**：即使修好 `_execute_task`（P0-1），Web 端「新建任务 → 执行」仍是死路；`/api/status.plugins` 也永远为空。
- **修复**：
  1. 启动时按 `discovered_names()` 全量加载（失败隔离，记录原因），或至少加载「任一任务引用到的插件」，不看 enabled；
  2. Web 执行入口改为 `scheduler.run_now(task_name)`（公开方法），内部校验插件是否存在并给出明确错误；
  3. 任务增删改后，对新增 plugin 做一次 `ensure_loaded`。
- **验证**：空任务配置启动 → `/api/status.plugins` 含 `qq`；Web 新建任务 → 点执行 → 返回 200 且日志出现 `notify_sending`。

### N3 [P0] 点击后不复验：存在发错群风险

- **位置**：`plugins/qq/plugin.py:149-157`（browse 分支）、`:162-187`（search 分支及其回退）
- **证据**：
  - browse 分支：`browse_to_group()` 返回坐标 → `pyautogui.click` → 直接 `get_input_target()`，**从不调用 `verify_chat_opened`**；
  - search 分支的回退（`:182-186`）点击后同样不复验，直接继续；
  - 唯一的群确认只发生在 search 主路径（`:162`），且只在「搜索直接成功」时校验。
- **影响**：OCR 误匹配、列表滚动错位、焦点被抢都可能把消息发到**其他会话**。这是自动化投递中最严重的一类事故（不可撤回、影响他人）。
- **修复**：
  1. 任何「点击以打开会话」的动作之后，**强制** `verify_chat_opened`；失败即中止（`retryable=True` + 失败截图），绝不继续；
  2. browse 分支命中多个候选时逐个点击并校验，而不是取第一个；
  3. 发送前增加一道「输入区确认」：前台窗口仍是 QQ、输入框可点击、群头 OCR 仍匹配；
  4. 配置加 `require_chat_verify: true`（默认开启，可关闭但需显式）。
- **验证**：把 `group_name` 改成不存在的群名 → 任务失败、无消息发出、`screenshots/failed/` 有截图；正常群名 → 成功。

### N4 [P1] 校准坐标语义不一致（标的是区域，点的是左上角）

- **位置**：`tools/calibrate.py:96-101`；`plugins/qq/locator.py:103-120`
- **证据**：calibrate 对每个色块输出 `relative_x/y/w/h`；但 `get_input_target()` 只取 `relative_x/y` 当点，`w/h` 被忽略。用户按「输入框区域」标注，代码点的是区域左上角，容易落在分隔线/边框上。
- **影响**：定位不稳、时好时坏；用户会误以为是 OCR 或 QQ 版本问题，反复重标。
- **修复**：统一语义——点类目标（输入框、搜索框）取 bbox 中心；区域类目标（校验区、联系人列表）才用 w/h；calibrate 的 `schema_hint` 与文档同步；`validate_config` 校验 0≤x,y≤1 且 x+w≤1。
- **验证**：dry-run 时在点击点画标记截图，确认落在输入框内。

### N5 [P1] 调度语义与健康检查噪音

- **位置**：`core/scheduler.py:74,146-156`；`plugins/qq/plugin.py:210-216`；`core/watchdog.py:66-71`
- **证据/影响**：
  1. 非重试失败被归为 `task_skipped`（`scheduler.py:152-156`）——日志会骗人，跳过与失败混为一谈；
  2. `retryable` 无消费者（P1-3 已提），此处补充：至少应在台账/告警中体现；
  3. 预通知用 `datetime.now(tz.utc)` 对本地时区 `CronTrigger` 求下次触发（`scheduler.py:74`），可能偏一个时区；
  4. 健康检查每 30s 检查一次，QQ 未开时**每 30s 重复告警**，且 `health_check` 只要标题含 "qq" 就判健康（`plugin.py:212-215`）；
  5. `add_task` 遇到坏 cron 直接抛 `ConfigValidationError`，`main.py` 无捕获 → **启动即崩**。
- **修复**：区分 busy/失败；retryable 接退避重试或明确不重试并写台账；统一 tz-aware 本地时间；健康检查只在状态跳变时告警；坏 cron 单任务跳过并 WARN，不阻断启动。

### N6 [P2] 窗口匹配过宽

- **位置**：`plugins/qq/locator.py:69-87`
- **证据**：标题包含子串 "qq" 即命中（大小写不敏感），QQ音乐、QQ浏览器、含 "qq" 的网页标题都会命中；`_force_foreground` 强制抢焦点。
- **影响**：把焦点抢到错误窗口，后续点击全部错位；多开 QQ 时也只命中第一个。
- **修复**：优先按进程名 + 窗口类名（如 `QQ.exe` / `TXGuiFoundation`）匹配，标题仅作兜底；多开时按标题中的账号后缀选择。

---

## 3. 与既有清单的合并草案（待确认后固化）

> 原则：同因合并、同症合并、跨层拆分。**保留原编号**，新增用 N 编号；被修改的条目标注 `[改]`，上调/移出的标 `[升]`/`[移]`。

### P0（3 → 5）

| 编号 | 内容 | 来源 |
|---|---|---|
| P0-1 `[改]` | Web 执行链路三处断：`_execute_task` 不存在 + 插件未加载 + 无错误提示 | 原 P0-1 + N2 |
| P0-2 | 纯文本任务不可发（D2 确认为 100% 需求） | 原 |
| P0-3 | 坐标/模板与当前 QQ 版本不匹配 | 原 |
| P0-4 | 实时日志流为空（监控假象） | 新增 N1 |
| P0-5 | 点击后不复验，存在发错群风险 | 新增 N3 |

### P1（8 → 12）

| 编号 | 内容 | 来源 |
|---|---|---|
| P1-1 | 配置热重载未接通 | 原 |
| P1-2 | 插件先注册后校验 | 原 |
| P1-3 | retryable 无消费者 | 原 |
| P1-4 | easyocr 中文路径陷阱（只传 ndarray） | 原 |
| P1-5 | 相对 cwd 路径（有打包计划，建议按 P0 排期） | 原 |
| P1-6 | 校验模板缺失应降级而非拒载 | 原 |
| P1-7 | 时区混用 | 原 |
| P1-8 | easyocr/torch DLL 偶发失败 | 原 |
| P1-9 | 发送前确认（群头 + 输入区 + 前台窗口），用 SSIM 实现 | 新增（与 P0-5 配套，D4） |
| P1-10 | dry-run（与 calibrate 合并为「试运行—截图—对比」闭环） | 原 P3-2 `[升]` |
| P1-11 | **checks 接入运行时**：check_loader 实例化、执行、结果进事件/日志/台账/UI | 原 P2-1 `[升]`（D3） |
| P1-12 | **WebUI 优化**：日志/状态/错误可见，任务编辑、运行历史、校准向导 | 新增（D5） |

### P2（7 → 9）

| 编号 | 内容 | 来源 |
|---|---|---|
| P2-1 `[移]` | `checks/` 死代码 → 已升 P1-11 | 原 |
| P2-2 | `locator` 两个死函数 | 原 |
| P2-3 | `group_name/message/images` 绕过 resolved_config | 原 |
| P2-4 | 失败截图目录未清洗任务名 | 原 |
| P2-5 | `requirements.txt` 与 `deps/*.txt` 不一致 | 原 |
| P2-6 | 前端无错误处理（`api()` 不查 `r.ok`），与 P1-12 的 UI-1 同批修 | 原 |
| P2-7 | 测试目录为空 | 原 |
| P2-8 | 校准坐标语义不一致 | 新增 N4 |
| P2-9 | 调度语义/健康检查噪音/坏 cron 阻断启动 | 新增 N5 |
| P2-10 | 窗口匹配过宽 | 新增 N6 |

> N4 若与 P0-3（重新校准）同批做，可直接并入 P0-3 的验收项；N5 中「坏 cron 阻断启动」建议单独提 P1。

### P3（原 5 → 4，dry-run 上调）

| 编号 | 内容 |
|---|---|
| P3-1 | 发送台账（作为 P1-11 的消费方一起做） |
| P3-3 | 多账号 / 多实例 |
| P3-4 | Web 鉴权（本地可先不做，绑 127.0.0.1 是现状） |
| P3-5 | 启动依赖检查阻塞（改为「缺依赖给明确指引」） |

> P3-2 dry-run → P1-10（唯一上调项）；P1-12 WebUI 为新增工作流，不占原编号。原清单其余 4 项保持原编号。

---

## 4. 项目定位与通道风险决策（回填 D1）

### 4.1 一句话定位

**AnySender 是本地优先、可观测、可审计的通知编排器；QQ 群是它最难的一个连接器，不是它存在的理由。**

这个定位带来四条硬约束：

1. **任务模型与通道解耦**：任务只描述「发什么、何时发、发到哪个通道」，不假设通道是 QQ；
2. **账号风险隔离在插件边界**：核心不读取、不存储、不代管任何账号凭证；凭证只在插件配置里，日志脱敏；
3. **通道分级**：高风险通道默认关闭，需用户在配置中显式启用，UI 上标注风险等级；
4. **能力边界自律**：不做账号池、不做营销群发、不做云端托管、不绕过验证码——这些既是合规红线，也是「市面上已有成品」的领域。

### 4.2 四层通道模型

| 层级 | 典型实现 | 账号风险 | 平台规则风险 | 技术脆弱性 | 默认状态 |
|---|---|---|---|---|---|
| **A 官方 API / Webhook** | 企微、钉钉、飞书、Telegram Bot、邮件、Gotify | 无（机器人凭证，不碰个人账号） | 中（内容审核、频率、资质） | 低 | 首选，默认可用 |
| **B 自托管协议端** | NapCat / OneBot 等 | **高**（登录态即账号） | 低（但违反平台协议） | 低 | 关闭，显式启用 |
| **C UI 自动化** | 本项目的 QQ 插件 | 中（行为层风险，非身份托管） | 中 | **高**（坐标/OCR/焦点） | QQ 群硬需求下启用 |
| **D 进程 Hook / 注入** | DLL 注入、内存补丁 | **高** | 低（法律边界模糊） | **高** | **排除**，不实现 |

### 4.3 QQ 群连接器的边界（Tier C）

**必须做到**：

- 群白名单（只允许配置里列出的群）；
- 发送前确认（P1-9）：窗口、群头、输入区三重 SSIM 校验；
- dry-run（P1-10）：只输入不发送，截图对比；
- 发送台账（P3-1）：每次运行可回放（时间、任务、结果、截图、check 明细）；
- 频率限制与人工确认：首次运行、账号异常后强制人工确认；
- 失败即停：任何校验失败都不得继续点击/输入。

**明确不做**：

- 自动加群、自动通过好友、私信群发、营销话术库；
- 保存 QQ 密码 / 扫码登录态 / 协议 token；
- 检测对抗（反截图、反调试、模拟真人轨迹）——这会把项目从「自动化工具」推向「外挂」。

> 措辞校正：C 类并非「零风险」，它仍然操作真实账号；但风险来源是**行为**而非**身份托管**，且完全发生在本机、可被用户随时中止。D1 的准确含义是「风险不由架构替用户承担」，不是「没有风险」。

### 4.4 决策记录与仍待定

**已定（D1–D5）**：见 0.1。

**仍待定**：

- [ ] B 类协议端是否作为「一等通道」实现，还是只留接口不实现？（建议：只留接口）
- [ ] WebUI 是否维持零构建（原生 JS）？（建议：维持，见 6.2）
- [ ] checks 的默认失败策略：pre_send 一律 block？（建议：block；warn 需显式配置）
- [ ] SSIM 校验区域与模板刷新策略：群头 + 输入栏，模板随校准向导更新？（建议：是）
- [ ] 台账存储形态：JSONL 文件 vs SQLite？（建议：JSONL，够用且可 diff）

---

## 5. checks 接入设计（P1-11，回填 D3）

### 5.1 现状

- `checks/base.py:35` 定义契约 `run(context) -> (bool, str)`；
- `checks/image_match.py`、`window_visible.py`、`json_schema.py` 三个实现完整；
- `core/check_loader.py:21-107` 能发现 `checks/` 与 `user_checks/`、支持同名覆盖、单文件失败隔离；
- **但全项目没有任何地方实例化 `CheckLoader`**，也没有任何 check 被执行过；`tests/` 为空。
- 三处重复实现：`image_match` 与 `plugins/qq/validator.py` 的 SSIM 算法几乎逐行相同；`window_visible` 与 `locator.enum_window_titles` 重复枚举窗口；`json_schema` 与 `validate_config` 的 Draft202012 校验重复。

### 5.2 接入原则

1. **保留契约**：Check 仍是无状态、平台无关、纯数据的单元，不 import 插件；
2. **成为运行时阶段**：check 不是装饰，是 `_do_work` 的前后置阶段；
3. **每次执行必有记录**：事件 + 结构化日志 + 台账 + UI 四处可见；
4. **默认 fail-closed**：`pre_send` 失败即中止，绝不带着失败继续点击；
5. **单点加载**：全进程一个 `CheckRunner`，启动时 discover 一次，支持热重载（可选）。

### 5.3 执行模型

新增 `core/check_runner.py`（约 120 行）：

```
CheckRunner(event_bus, logger)
  ├─ discover()                      # 包装 CheckLoader，把 print 改成事件/日志
  ├─ run(phase, context, plan)       # 顺序执行，聚合 CheckReport
  └─ report                          # {passed, results:[{name,phase,passed,detail,ms}], blocked}
```

执行位置在 `core/scheduler.py:_do_work`（`:129-162`）：

```
pre_send  → send_with_lock → post_send
```

- 上下文由调度器构造：`{task, plugin_name, resolved_config, run_id}`；
- 需要截图的 check（image_match）由插件提供 `build_check_context(phase, task)`，返回 `{screenshot, template, min_similarity, ...}`；插件不实现则跳过需要图像的 check 并 WARN；
- `plan` 来自任务配置（5.5），为空则只跑插件声明的默认 check（可选）。

QQ 插件的建议默认计划：

| 阶段 | check | 作用 |
|---|---|---|
| pre_send | `window_visible` | QQ 在前台且标题匹配 |
| pre_send | `image_match`（群头模板） | 当前会话就是目标群 → 直接实现 P0-5/P1-9 |
| post_send | `image_match`（输入框清空/消息出现） | 替代 `validator.py` 的重复实现 |

### 5.4 事件、日志与台账

新增两个事件，字段与现有事件风格一致：

```
check_result: task_name, plugin_name, check_name, phase,
              passed, detail, duration_ms, artifacts
```

- `core/logger.py:109-115` 增加订阅；`LOG_RECORD_ATTRS`（`:11-14`）增加 `check_name/phase/passed`，RingHandler 与 JSON 文件自动带上；
- 失败时额外发一条 `task_failed`（`detail` 前缀 `[check:xxx]`），成功则并入 `task_completed.detail` 的摘要；
- 台账（P3-1）直接消费同一事件，不需要 check 层单独写文件；
- `CheckLoader` 的 `print` 全部替换为 `logger.info/warning`，加载失败发 `check_load_failed` 事件。

### 5.5 配置与 schema

任务级新增（`config/tasks.yaml` 与 `schemas/default/tasks.json`）：

```yaml
checks:
  - name: window_visible
    phase: pre_send
    on_fail: block
    params: { keywords: ["QQ"] }
  - name: image_match
    phase: pre_send
    on_fail: block
    params: { region: chat_header, min_similarity: 0.86 }
```

- `on_fail: block | warn`，默认 `block`；
- 未配置 `checks` 时：保持当前行为（不跑 check），避免升级破坏老任务；
- `user_checks/` 同名覆盖时打 INFO 日志，并标记 `source: user`。

### 5.6 SSIM 的适用边界（D4）

保留 SSIM 的原因：QQ 主题、DPI、字体渲染的小改动会让「关键元素模板匹配」大面积失效；整块区域的 SSIM 对亮度（CLAHE）、噪声（Blur）、边缘（Canny）做了归一，鲁棒性更好。但它有明确边界，必须按边界使用：

- **只用稳定区域**：群头（群名 + 成员数）、输入栏；**不要用消息流**（滚动、新消息、时间戳会让分数抖动）；
- **模板要有生命周期**：校准向导截取，记录 `captured_at` 与 QQ 版本；超过 30 天或 QQ 更新后提示重截；
- **双阈值**：`pass ≥ 0.86`、`warn ≥ 0.78`；warn 记日志但放行，需显式配置；
- **与窗口检查组合**：窗口错了，图像分数再高也没意义；
- **禁止单靠 SSIM 做「发送成功」判定**：发送成功以「输入框清空 + 消息区出现新气泡」或人工确认为准，SSIM 只做辅助。

### 5.7 验收

1. 启动日志出现「加载 N 个 check（builtin=3, user=M）」；
2. 任意任务运行后，`logs/anySender.log` 出现 `check_result` 行，SSE 实时可见；
3. 把群头模板换成别的群 → `pre_send` block，无消息发出，失败截图存在；
4. `user_checks/` 放一个同名 check → 日志出现 override，且行为使用用户版本；
5. 单测：三个 check 各 2 个用例（通过/失败）+ runner 的 block/warn 聚合。

---

## 6. WebUI 优化计划（P1-12，回填 D5）

### 6.1 现状问题

1. SSE 日志流永远为空（N1），面板是装饰；
2. 前端 `api()` 不检查 `r.ok`，后端 500 时界面无反应；
3. 状态球硬编码「运行中」，不反映真实健康；
4. 无运行历史、无台账视图，刷新即丢；
5. 无 checks 结果展示；
6. 无 dry-run、无校准入口；
7. 任务编辑器：cron 无预览/校验，`plugin_config` 无 schema 表单，图片路径手填；
8. 无错误提示、无重试、无 loading 状态；
9. 日志不能暂停/过滤/导出；「清空」只清 DOM；
10. 单栏布局、无空状态、无明显的信息层级；
11. 前端零测试；
12. 无鉴权（本地可接受，但至少绑 127.0.0.1 + 可选 token）。

### 6.2 原则

- **零构建**：原生 ES modules + 少量工具函数；不引入 React/Vite，不给 Python 项目加 Node 工具链；
- **API-first**：每个 UI 状态都有对应 endpoint，界面不猜；
- **错误必须可见**：统一 fetch wrapper，失败 toast + 日志 + 可复制错误；
- **可确认、可回放**：删除、立即执行、dry-run 都要有确认与结果；
- **可访问性最低线**：键盘可达、对比度、日志区 `aria-live="polite"`。

### 6.3 分期

| 阶段 | 内容 | 验收 |
|---|---|---|
| **UI-1 基础修复**（随 P0 批次） | fetch wrapper；状态面板接真实数据（插件/下次运行/最近结果）；SSE 修复 + 自动重连 + 暂停；执行按钮 loading/禁用；清空日志改服务端或明示仅清屏 | 后端 500 时界面有红色提示；日志 1s 内滚动；状态 5s 内刷新 |
| **UI-2 任务编辑器 v2** | 插件配置 schema-driven 表单；cron 预览（下次 5 次）；图片/模板路径校验 + 缩略图；checks 可视化配置；复制任务；启停开关 | 新建任务无需手写 YAML；非法 cron 即时提示 |
| **UI-3 运行视图** | 运行历史表（时间/任务/结果/耗时/摘要）；详情抽屉（截图、check 明细、原始日志）；手动重跑；导出 JSON | 重启后历史仍在；失败可一键重跑 |
| **UI-4 校准向导** | 截屏 → 画框 → 显示点击点/区域 → 保存 `config/plugins/qq.yaml` → 生成模板；复用 `tools/calibrate.py` 的 HSV 逻辑 | 10 分钟内完成一次重校准；dry-run 一次成功 |
| **UI-5 打磨** | 设计 token（颜色/间距/字号）；空状态/骨架屏；响应式最小可用；键盘快捷键；深色模式（可选） | 1280×720 无横向滚动；无 console 错误 |

### 6.4 后端配套接口（新增/修改）

| 接口 | 用途 |
|---|---|
| `POST /api/tasks/<name>/run` | 改为调用 `scheduler.run_now()`，返回 `run_id`；插件缺失返回 409 + 明确原因 |
| `GET /api/runs?limit=50` / `GET /api/runs/<id>` | 运行历史与详情（台账） |
| `GET /api/checks` / `POST /api/checks/<name>/test` | check 列表与手动试跑（可选） |
| `GET /api/tasks/<name>/next-runs?n=5` | cron 预览 |
| `GET /api/plugins/<name>/schema` | 生成配置表单 |
| `GET /api/status` | 扩展：插件健康、最近结果、下次运行、check 计数 |
| `GET /api/events`（统一 SSE） | 日志 + task/check 事件，带 `id:` 支持断线续传 |
| 统一错误体 | `{ok:false, error:{code, message, detail}}` |

### 6.5 不做

用户系统、多租户、云同步、富文本编辑器、移动 App；这些会把「本地工具」变成「平台产品」，与 D1 的定位相反。

---

## 7. 施工顺序（草案）

```
第 0 批（今天，10 分钟）
  git add issue/；删除 Anysender 杂散目录；确认 D1–D5 回填

第 1 批（纯代码，2–3 小时）
  P0-4 日志环 → P0-1 + N2 Web 执行链路 → P1-2 注册顺序
  → P1-5 绝对路径 → P1-6 模板降级 → P0-2 纯文本
  → P1-9/P0-5 发送前确认 → UI-1

第 2 批（校准链路）
  P1-10 dry-run（与 calibrate 合并）→ P0-3 重新校准
  → P2-8 坐标语义统一（同批验收）

第 3 批（checks）
  P1-11 CheckRunner + 事件/日志 → 去重 validator/locator/schema
  → UI-3 的 check 明细

第 4 批（WebUI v2）
  UI-2 编辑器 → UI-3 运行视图 + /api/runs → UI-4 校准向导 → UI-5

第 5 批（可靠性）
  P1-1 热重载 → P1-3 退避重试/台账 → P1-7 时区
  → P1-8 OCR 重试 → P2-9 调度语义与健康检查 → P3-1 台账

第 6 批（清理）
  P2-5 依赖清单 → P2-2 死函数 → P2-4 文件名清洗
  → P2-10 窗口匹配 → P3 鉴权/多账号

每批完成以「验收」为准，不新增功能。
```

---

## 8. 仓库卫生现状（与旧结论的差异）

| 项 | 现状 | 建议 |
|---|---|---|
| `AnySender - 副本/` | **已不存在** | 归档时标记已清理，不再列为待办 |
| `AnySender/Anysender/` | 仅 `.gitattributes` + `LICENSE` | 删除 |
| 根目录 v1 文件 | `qq_auto_send.py`、`config.json`、`QQautoBot.spec`、`requirements.txt` 等已被 `.gitignore` 排除，但仍在工作区 | 移入 `legacy/` 或删除；至少避免与 v2 混淆 |
| 84MB 模型包 | `PP-OCRv5_server_rec_infer.tar`（未跟踪，`.gitignore` 已忽略 `*.tar`） | 确认无引用后删除 |
| `build/`、`dist/` | 未跟踪产物 | 删除；打包按需重建 |
| `issue/` | 未入库（`git status` 显示 `?? issue/`） | `git add issue/`，纳入版本管理 |
| `tests/` | 空目录，无 pytest | 至少补 3 个冒烟测试：cron 解析、配置深合并、SendResult 分类；P1-11 再加 check 单测 |
| `logs/` | `anySender.log` 停在 2026-08-10，`errors.log` 停在 05-12 | 归档旧日志，避免误判「最近运行过」 |
| `requirements.txt` | 与 `deps/*.txt` 不一致（缺 flask/easyocr/pyperclip/windows-toasts，多 winotify） | 以 `deps/*.txt` 为唯一来源，requirements 由它汇总生成 |

---

## 9. 验收口径

### 9.1 P0

| 编号 | 验收动作 | 期望 |
|---|---|---|
| P0-1 | Web 新建任务 → 点「执行」 | HTTP 200；日志出现 `notify_sending`；`/api/status.plugins` 含 `qq` |
| P0-2 | `images: []` + 非空 `message` | 文本成功送达 |
| P0-3 | 重新校准后 search 模式连续 3 次 | 均进入正确群，群头 OCR 全部命中 |
| P0-4 | `curl -N /api/logs/stream` | 1s 内收到至少一条 `data:` |
| P0-5 | 群名改成不存在的值执行 | 任务失败、**无消息发出**、失败截图存在 |

### 9.2 新增工作流

| 编号 | 验收动作 | 期望 |
|---|---|---|
| P1-11 | 启动 + 运行一次任务 | 日志有 check 加载计数与 `check_result`；SSE 可见；block 生效 |
| P1-12 | 冷启动 → 新建任务 → 执行 → 看结果 → 重跑 | 全程不写 YAML、不看终端；错误有提示；历史可回放 |

---

## 10. 我的总评（写进归档的结论）

- **定位对齐后，架构的「过度设计」变成「必要预留」**：通道插件化本来是为多平台准备的，在 D1 下不再是多余的抽象，而是「风险分层」的载体。核心不托管账号、不假设平台，这正是它和市面上成品的分野。
- **架构 8/10**：分层、契约、降级链、通知闭环成立，`core/` 禁 GUI 的纪律是真实约束而非口号。
- **工程 5/10**：测试为零、文档漂移、死代码、依赖清单打架、路径与 cwd 耦合。
- **可用性 3/10**：按当前 QQ 版本，主链路仍卡在「定位 + 校准 + 结果可信」。
- **竞争力不在「绕过检测」**，而在本地优先、可审计、dry-run、可组合 checks、多通道——这些是云服务给不了的，也是 D1 的自然推论。
- **主要矛盾**：不在架构，而在最后一公里——把「能发对、能证明发对了」做出来，比继续加抽象层有价值一个数量级。
- **成功判据**：连续 7 天定时发送零错群；每次运行可回放；Web 能解释「为什么这次没发」；换一台同版本 Windows 机器，重校准后 30 分钟内跑通。

---

> 参考：`issue/AnySender-审查报告.md`（全貌）、`AnySender-Bug分级.md`（23 项施工单）、`AnySender-UI分析.md`（U1–U12）、`AnySender-复核意见与施工建议.md`（复核与排序）。
> 本文编号 N1–N6 为新增，与旧编号并存；合并方案待你确认后再回写进 `Bug分级`，避免两套编号长期并行。
