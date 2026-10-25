# AnySender 复核意见与施工建议

> 范围：`E:\QQautoBot\AnySender`
> 依据：对同目录 `AnySender-审查报告.md`、`AnySender-Bug分级.md` 的实地复核（抽查约 10 个关键论断，逐条对照当前源码 + git 历史 + 日志）
> 日期：2026-10-26 ｜ 代码版本：`90c4479`（HEAD，工作区干净）
> 结论先行：**两份文档全部论断核验属实，无夸大、无过时**；本文只补充它们没点透的问题和微调后的施工顺序。

---

## 一、最重要的事实：代码停在被审查的那一刻

- `git log` 显示 HEAD 正是审查基准 `90c4479`（2026-10-23 04:41「文档纠错 + 接入 Web 控制台」），工作区干净——**审查后 3 天，23 个问题一个都没修**，Bug 分级清单现在仍是 100% 有效的 backlog。
- `logs/anySender.log` 最后一条是 8/10 的启动记录，程序自那以后没再跑过；`config/tasks.yaml` 里 test 任务 `enabled: false`，与审查报告对 8/10 日志的解释完全吻合。

### P0-1 是最新提交自己生的（审查报告未点破）

`web/` 整个目录（含 173 行的 `app.py`）是 `90c4479` **新增**的。也就是说 Web 控制台从出生那天起「立即执行」就是坏的：

- `web/app.py:118` 调用 `_scheduler._execute_task(t)`，全项目 grep 该方法名仅 2 处——app.py 这一处调用 + `ARCHITECTURE.md:557` 的「已知问题」标注。
- 同一提交在 `ARCHITECTURE.md:557-558` 把「立即执行不可用」「热重载未接通」写进了已知问题表。

**作者知道问题存在，选择记录而不是修复。**这是典型的"文档先行、修复欠账"状态。

---

## 二、对两份文档的评价

| 文档 | 评价 |
|---|---|
| 审查报告 | 质量高。抽查核对全部属实：`plugin_manager.py:69-74` 先注册后校验、`scheduler.py:74` 的 `datetime.now(tz.utc)`、`main.py:40/45` 相对路径、`plugin.py:140` images 硬门槛、requirements.txt 误列 winotify 等 |
| Bug 分级清单 | 可直接当施工单用；P0→P1→P2 顺序合理，唯一排错级别的是 P3-2（见下文第 1 条） |

历史失败解释链交叉印证可信：5 月日志来自**旧版实现**——`logs/errors.log` 最后一条 `Engine 'hpi' is unavailable because dependency 'ultra-infer' is not installed` 是 RapidOCR 系的报错，而当前代码用 easyocr，佐证"当时是另一套代码"的推断。

---

## 三、原文档没充分强调的四点（本文补充）

### 1. P3-2（dry-run）应升级为 P1 —— 清单里唯一排错级别的项

P0-3 重新校准是整个项目真正的"鬼门关"：需要人工截图、标注、反复试。没有 dry-run，每试一次就往「飞鱼的记事本」真发一条消息。先做 dry-run（走到"定位到群 + 填好输入框"就停），P0-3 的校准成本会降一个量级。**先修 P3-2，再做 P0-3。**

### 2. P2-3 比看起来更隐蔽

`plugin.py:130-132` 从 `task["plugin_config"]` 直接取 group_name/message/images，其余参数走 `task["resolved_config"]`（插件级配置已合并进去）。当前 tasks.yaml 恰好把群名写在任务里所以能跑，但 `config/plugins/qq.yaml` 里的默认值**永远不生效**——三级深合并体系被这一处短路，将来必踩。

### 3. 仓库卫生：副本目录是最大隐患

- `E:\QQautoBot\AnySender - 副本\` 是整个项目的复制目录（审查刻意跳过）。哪天改错目录，所有修复都白费。**建议尽快删除或移出仓库根。**
- `AnySender\Anysender\` 还有个只含 LICENSE 的嵌套杂散目录，一并清理。

### 4. P1-5（相对路径）与打包计划冲突，实际接近 P0

项目里有 `AnySender.spec` + `build.bat`（PyInstaller 打包），还有 `build/`、`dist/` 产物目录。一旦打成 exe 双击运行，cwd 是 `system32` 或桌面，`ConfigHub("config","presets")`、`PluginManager("plugins")`、`log_dir="logs"` 全部读不到/写飞。**在有打包计划的前提下这条应按 P0 对待。**

---

## 四、对架构本身的看法

设计是清醒的：core 禁 GUI、插件化、三级降级定位链（搜索 → OCR 下拉 → 列表遍历）、用 OCR 校验聊天头绕开 QQ9 标题恒为 `QQ` 的问题——这些选择都对。

但它是 UI 自动化的固有脆弱性载体：

- 坐标耦合 QQ 版本，QQ 一更新就得重校准；
- 运行期独占前台键鼠，人不能操作电脑；
- 单实例单 QQ 窗口，多账号需多进程。

**这类项目的可靠性上限不在代码质量，而在外部界面的稳定性。**因此：

- **值得修**：目标若是给自己/固定群发通知广告，修完 P0+P1 后完全够用；
- **不值得过度投入**：多账号、Web 鉴权等 P3 项除非需求真来了否则别做，UI 自动化方案的边际收益递减很快。

---

## 五、微调后的施工顺序

```
第一批（纯代码，约 1-2 小时，全部机械小改）：
  P0-1（web/app.py:118 改调 _on_main_trigger 或加 run_now）
  → P0-2（images 改可选，message/images 至少一个非空）
  → P1-5（chdir 或全面绝对路径化 —— 因打包计划按 P0 对待）
  → P1-2（validate_config 前置，失败不写入注册表）
  → P1-6（模板缺失降级为跳过校验 + WARN，而非拒绝加载）
  → P2-3（group_name/message/images 统一走 resolved_config）

第二批（校准链路）：
  P3-2 dry-run（从 P3 升级，先行）
  → P0-3 重新校准（人工截图标注 + tools/calibrate.py --desaturate + 新校验模板）

第三批（可靠性）：
  P1-1（Scheduler 订阅 config_changed 实现热重载）
  → P1-3（retryable 消费：退避重试或明确文档化不重试）
  → P1-7（时区统一 tz-aware 本地时间）
  → P1-8（easyocr.Reader 初始化重试 2-3 次）

顺手清理：
  删 AnySender - 副本、Anysender 杂散目录
  同步 requirements.txt 与 deps/*.txt（补 flask/easyocr/pyperclip/windows-toasts，删 winotify）
```

每批修完按 Bug 分级清单里对应条目的「验证」标准自查。

---

> 参考：`issue/AnySender-审查报告.md`（架构与问题全貌）、`issue/AnySender-Bug分级.md`（23 项分级施工单）。
