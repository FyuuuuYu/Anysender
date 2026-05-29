# schemas/ — 插件配置 JSON Schema 存放目录
#
# 查找优先级（高 → 低）：
#   schemas/<plugin_name>.json         用户自定义 schema
#   schemas/default/<plugin_name>.json 内置默认 schema
#   插件代码 get_default_config()      代码级兜底
#
# 用户只需在 schemas/ 下放入同名 json 文件即可覆盖默认校验规则
