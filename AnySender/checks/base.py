"""
Check 抽象基类

所有校验模块必须继承 Check，实现 run(context) -> (bool, str)。
context 是平台无关的数据字典，由插件调用方构造。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple


class Check(ABC):
    """
    可组合校验单元。

    使用方式:
        check = SomeCheck()
        ok, detail = check.run({"key": value, ...})

    约定:
        - 不依赖 core/ 或任何具体插件
        - run() 是纯数据变换，无副作用（文件 I/O 除外）
        - 返回值: (通过: bool, 详情: str)
    """

    @abstractmethod
    def get_name(self) -> str:
        """
        全局唯一名称。如 "image_match"、"window_visible"。
        与 user_checks/ 中的文件名一致时，用户版本覆盖内置版本。
        """
        ...

    @abstractmethod
    def run(self, context: Dict[str, Any]) -> Tuple[bool, str]:
        """
        执行校验。

        Args:
            context: 平台无关的输入字典。调用方负责填入正确数据。

        Returns:
            (passed, detail): passed=True 表示校验通过，detail 为补充描述。

        Raises:
            KeyError: 缺少必需的 context 键时抛出，调用方应捕获并标记为配置错误。
        """
        ...

    def __repr__(self) -> str:
        return f"<Check:{self.get_name()}>"
