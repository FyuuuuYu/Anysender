# AnySender v2.0

通用自动化发送框架 —— 插件化、配置驱动、Windows 通知交互

## 当前进度

| 模块 | 状态 |
|------|------|
| core/ 核心框架 | ✅ |
| plugins/qq 插件 | 🟡 精确搜索+遍历实现，定位&OCR 调试中 |
| notifier 通知 | ✅ Windows toast 两级提醒 |
| deps 依赖管理 | ✅ 自动检测+按需安装 |
| tools/calibrate 校准 | ✅ HSV 色相五区域标定 |
| 打包 exe | ✅ PyInstaller |

**待完成**：QQ 搜索定位校准、遍历 OCR 匹配精度调优。

## 快速开始

```bash
cd AnySender
python setup.py          # 安装依赖
python setup.py --run    # 直接启动
python setup.py --build  # 打包 exe
```

## 目录

```
AnySender/
├── core/          # 核心框架（零 GUI 依赖）
├── plugins/       # 内置插件（qq / wechat / dingtalk / feishu）
├── notifier/      # Windows 通知
├── tools/         # 校准工具
├── deps/          # 依赖管理
├── config/        # 用户配置
├── presets/       # 出厂预设
├── schemas/       # 校验规则
├── main.py        # 入口
├── setup.py       # 一键安装/启动/打包
└── ARCHITECTURE.md
```

详见 [ARCHITECTURE.md](AnySender/ARCHITECTURE.md)。
