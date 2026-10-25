# AnySender Bug 清单 v2（归档版）

> 目标：`E:\QQautoBot\AnySender` ｜ 代码版本：`90c4479` ｜ 日期：2026-10-26
> 来源：`AnySender-Bug分级.md`（v1，23 项）+ `AnySender-补充审查意见与归档草案.md`（N1–N6、D1–D5）
> 状态：**全部 open**（截至 `90c4479`，无任何修复提交）
> 说明：本文件是合并后的**唯一施工清单**；v1 保留为历史记录，不再更新。

## 分级标准

| 级别 | 含义 | 处理时机 |
|---|---|---|
| **P0** | 功能不可用 / 核心需求直接失效 | 必须修，否则跑不起来 |
| **P1** | 静默失效、可靠性隐患，出问题很难察觉 | 上线前修 |
| **P2** | 一致性、健壮性、可维护性问题 | 迭代中修 |
| **P3** | 改进建议，不影响当前使用 | 有余力再做 |

## 统计

| 级别 | 数量 | 变化 |
|---|---|---|
| P0 | 5 | +2（N1、N3）；P0-1 吸收 N2 |
| P1 | 12 | +4（P1-9/10/11/12） |
| P2 | 9 | -1（P2-1 升 P1-11）+3（N4–N6） |
| P3 | 4 | -1（dry-run 升 P1-10） |
| **合计** | **30** | 旧 23 + 新增 7 个编号 |

---

## P0 — 阻断级（5）

| 编号 | 问题 | 位置 | 修复要点 | 验收 | 批次 |
|---|---|---|---|---|---|
| P0-1 | Web「立即执行」必崩 + 插件未加载 | `web/app.py:118`；`main.py:52-59` | 新增 `Scheduler.run_now(name)`；插件按 discovered 全量加载（失败隔离）；错误明确返回 | 新建任务→执行返回 200，日志有 `notify_sending`，`/api/status.plugins` 含 `qq` | 1 |
| P0-2 | 纯文本任务无法发送（D2：100% 需求） | `plugins/qq/plugin.py:140` | `images` 可选；`message` 与 `images` 至少一个非空；空 images 跳过粘贴 | `images: []` + `message` 能送达 | 1 |
| P0-3 | 坐标/模板与当前 QQ 版本不匹配 | `config/plugins/qq.yaml` | 重校准（红绿蓝黄紫标注 + `--desaturate`）+ 重截校验模板 | search 模式连续 3 次进对群、群头校验通过 | 2 |
| P0-4 | 实时日志流永远为空（N1） | `core/logger.py:49,62,72`；`web/app.py:126-132` | `Logger._ring` 与 `RingHandler._ring` 共享同一 deque；SSE 加心跳/续传 | `curl -N /api/logs/stream` 1s 内收到 `data:` | 1 |
| P0-5 | 点击后不复验，存在发错群风险（N3） | `plugins/qq/plugin.py:149-157,162-187` | 任何「点击打开会话」后强制 `verify_chat_opened`；失败即停；browse 多候选逐个校验；`require_chat_verify` 默认 true | 群名改为不存在值：任务失败、**无消息发出**、有失败截图 | 1 |

## P1 — 严重（12）

| 编号 | 问题 | 位置 | 修复要点 | 验收 | 批次 |
|---|---|---|---|---|---|
| P1-1 | 配置热重载未接通 | `core/watchdog.py:64`；无订阅 | `Scheduler` 订阅 `config_changed`，移除旧 job 按新配置重建 | 改 cron 等 300s 后 `/api/status.next_runs` 变化 | 5 |
| P1-2 | 插件先注册后校验 | `core/plugin_manager.py:68-74` | `validate_config()` 提到注册之前；失败不写入字典 | 非法 `luma_weight` 时 `loaded_names()` 为空 | 1 |
| P1-3 | `retryable` 无消费者 | `core/scheduler.py:146-151` | 退避重试 3 次（10/30/60s）或明确不重试并写入台账 | 故障注入后按策略重试，台账有记录 | 5 |
| P1-4 | easyocr 中文路径陷阱 | `plugins/qq/browser.py` | 统一「只传 numpy」；`_ocr_region` 入口断言 ndarray | 中文路径不再触发 `readtext` 报错 | 5 |
| P1-5 | 所有路径相对 cwd | `main.py:40,45`；`core/logger.py:77` | 全部改为基于 `__file__` 的绝对路径 | 从 `C:\` 或快捷方式启动仍读写正确 | 1 |
| P1-6 | 校验模板缺失导致插件拒载 | `plugins/qq/plugin.py:96-100` | 模板无效时自动 `validation.enabled=false` + WARN，不拒载 | 删除模板后插件仍加载，截图存档 | 1 |
| P1-7 | 时区混用 | `core/scheduler.py:74` | `ZoneInfo(self._timezone_str)` 统一 tz-aware 本地时间 | 预通知在配置时区正确触发 | 5 |
| P1-8 | easyocr/torch DLL 偶发失败 | `plugins/qq/browser.py:22` | `_get_reader()` 重试 2–3 次，失败降级 browse | 连续启动 10 次无 WinError 1114 中断 | 5 |
| P1-9 | 发送前无「群/输入区」确认 | 新增（QQ 插件） | `pre_send`：窗口 + 群头 + 输入区三重 SSIM（复用 P1-11），默认 block | 错群/错窗口时零发送 | 1 |
| P1-10 | 无 dry-run | 新增（P3-2 上调） | 定位 + 填输入框即停，不回车；截图对比；与 calibrate 合并 | dry-run 后群内无新消息，截图齐全 | 2 |
| P1-11 | `checks/` 死代码（D3：接入日志） | `core/check_loader.py`；`checks/*` | `CheckRunner` 实例化；pre/post 阶段执行；`check_result` 事件进 Logger/SSE/台账；去重 validator | 启动日志有 check 计数；运行后日志/SSE 有 `check_result`；block 生效 | 3 |
| P1-12 | WebUI 不可用/不可观测（D5） | `web/` | UI-1 基础修复 → UI-2 编辑器 → UI-3 运行视图 → UI-4 校准向导 → UI-5 打磨（详见补充文档第 6 节） | 冷启动全流程不写 YAML；错误可见；历史可回放 | 1/4 |

## P2 — 一般（9）

| 编号 | 问题 | 位置 | 修复要点 | 验收 | 批次 |
|---|---|---|---|---|---|
| P2-2 | `locator` 两个死函数 | `plugins/qq/locator.py:90,162` | 删除；`verify_group_chat_opened` 已被 browser 版取代 | 全项目无引用 | 6 |
| P2-3 | 配置来源不一致 | `plugins/qq/plugin.py:130-132` | `group_name/message/images` 统一走 `resolved_config` | `qq.yaml` 默认群名生效 | 6 |
| P2-4 | 失败截图目录用任务名 | `plugins/qq/plugin.py:224` | slugify（`:` `?` `*` `/` → `_`），截断长度 | 含特殊字符的任务名不抛异常 | 6 |
| P2-5 | 依赖清单不一致 | `requirements.txt` vs `deps/*.txt` | 以 `deps/*.txt` 为唯一来源生成；删除 winotify | 干净机器按清单安装可启动 | 6 |
| P2-6 | 前端无错误处理 | `web/static/app.js:3-11` | 统一 fetch wrapper，检查 `r.ok`，toast + 可复制错误 | 后端 500 时界面有红色提示 | 1 |
| P2-7 | 测试目录为空 | `tests/` | 冒烟 3 个：cron 解析、配置深合并、SendResult 分类；P1-11 加 check 单测 | `pytest` 全绿 | 6 |
| P2-8 | 校准坐标语义不一致（N4） | `tools/calibrate.py:96-101`；`plugins/qq/locator.py:103-120` | 点类目标取 bbox 中心；区域类才用 w/h；校验 0≤x,y 且 x+w≤1 | dry-run 标记点落在输入框内 | 2 |
| P2-9 | 调度语义/健康检查噪音/坏 cron（N5） | `core/scheduler.py:74,146-156`；`plugins/qq/plugin.py:210-216`；`core/watchdog.py:66-71` | 区分 busy/失败；健康仅状态跳变告警；坏 cron 单任务跳过 WARN | 坏 cron 不阻断启动；QQ 未开只告警一次 | 5 |
| P2-10 | 窗口匹配过宽（N6） | `plugins/qq/locator.py:69-87` | 优先进程名 + 窗口类名（QQ.exe / TXGuiFoundation），标题兜底 | 只命中 QQ，不误抢 QQ音乐/浏览器 | 6 |

## P3 — 改进建议（4）

| 编号 | 问题 | 修复要点 | 验收 | 批次 |
|---|---|---|---|---|
| P3-1 | 无发送台账 | JSONL：run_id、任务、通道、群、时间、结果、截图、check 摘要 | 每次运行可回放；Web 运行视图可读 | 5 |
| P3-3 | 多账号需多进程 | 按标题/进程实例选择目标窗口；文档化单实例限制 | 双开 QQ 可指定窗口发送 | 后 |
| P3-4 | Web 无鉴权 | 保持绑 `127.0.0.1`；可选 token；禁止 `0.0.0.0` | 非本机访问被拒绝 | 后 |
| P3-5 | 启动依赖检查阻塞 | 缺依赖给明确安装指引，后台安装或首次提示 | 首次启动不卡几十秒 | 6 |

---

## 变更映射（v1 → v2）

| v1 | v2 | 说明 |
|---|---|---|
| P0-1 | P0-1 | 吸收 N2（插件加载） |
| P0-2 / P0-3 | P0-2 / P0-3 | 不变 |
| — | P0-4 | N1 日志死环 |
| — | P0-5 | N3 点击后不复验 |
| P1-1…P1-8 | P1-1…P1-8 | 不变 |
| — | P1-9 | 发送前确认（配合 P0-5，D4） |
| P3-2 | P1-10 | dry-run 上调（复核意见） |
| P2-1 | P1-11 | checks 接入（D3） |
| — | P1-12 | WebUI 优化（D5） |
| P2-2…P2-7 | P2-2…P2-7 | 不变 |
| — | P2-8 / P2-9 / P2-10 | N4 / N5 / N6 |
| P3-1 / P3-3 / P3-4 / P3-5 | 同编号 | 不变 |

## 批次汇总

| 批次 | 内容 | 项数 |
|---|---|---|
| 0 | 仓库卫生：`git add issue/`、删杂散目录、归档旧日志 | — |
| 1 | 代码闭环：P0-1/2/4/5、P1-2/5/6/9、P2-6、UI-1 | 10 |
| 2 | 校准：P0-3、P1-10、P2-8 | 3 |
| 3 | checks：P1-11 + 三处去重 | 1 |
| 4 | WebUI：UI-2…UI-5 + `/api/runs` 等 | 1 |
| 5 | 可靠性：P1-1/3/4/7/8、P2-9、P3-1 | 7 |
| 6 | 清理：P2-2/3/4/5/7/10、P3-5 | 7 |

## 附：待定项（不影响开工）

- [ ] B 类协议端只留接口，还是实现一等通道？（建议只留接口）
- [ ] WebUI 维持零构建？（建议维持）
- [ ] checks 默认 `on_fail: block`？（建议是）
- [ ] SSIM 区域 = 群头 + 输入栏，模板随校准更新？（建议是）
- [ ] 台账 JSONL vs SQLite？（建议 JSONL）

> 详细设计见 `AnySender-补充审查意见与归档草案.md` 第 4–6 节；验收口径见第 9 节。
