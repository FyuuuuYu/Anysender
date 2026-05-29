# AnySender v2.0

通用自动化发送框架 —— 插件化、配置驱动、Windows 通知交互

## 当前进度

| 模块 | 状态 |
|------|------|
| core/ 核心框架 | ✅ 完成 |
| plugins/qq 插件 | 🟡 精确搜索+遍历均实现，定位&OCR 调试中 |
| notifier 通知 | ✅ Windows toast 两级提醒 |
| deps 依赖管理 | ✅ 自动检测+按需安装+版本回退 |
| tools/calibrate 校准 | ✅ HSV 色相五区域标定 |
| 打包 exe | ✅ PyInstaller spec + build.bat |

**待完成**：QQ 搜索定位校准、遍历 OCR 匹配精度调优（easyocr 已接入，待端到端验证）。

## 快速开始

```bash
# 1. 安装依赖
python setup.py

# 2. 配置任务
#    编辑 config/tasks.yaml（示例参考 presets/tasks.yaml）

# 3. 启动
python main.py
```

## 打包为 exe

```bash
python setup.py --build
# 产物：dist/AnySender.exe
# 运行时需保持 config/ presets/ schemas/ 目录与 exe 同级
```

## 目录结构

```
AnySender/
├── main.py                 # 入口
├── setup.py                # 一键安装/构建/启动
├── AnySender.spec          # PyInstaller 配置
├── build.bat               # 备用打包脚本
│
├── core/                   # 核心框架（零 GUI 依赖）
├── plugins/                # 内置插件
│   ├── _base/              # 公共基类（剪切板锁）
│   └── qq/                 # QQ 插件
├── custom_plugins/         # 用户自定义插件
├── schemas/                # 校验规则
├── config/                 # 用户配置
├── presets/                # 出厂预设
├── deps/                   # 依赖管理
├── tools/                  # 校准工具
├── notifier/               # Windows 通知（windows-toasts）
│
├── logs/                   # 运行日志
├── screenshots/            # 截图（temp/failed/done/reference）
└── tests/
```

## 依赖

| 分组 | 内容 |
|------|------|
| core | APScheduler, PyYAML, jsonschema |
| qq | pyautogui, opencv-python, pywin32, scikit-image, Pillow, pyperclip, easyocr |
| notify | windows-toasts |

安装：`python setup.py`（自动按需安装，版本不兼容自动回退）
