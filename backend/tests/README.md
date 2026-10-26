# 测试目录

本目录用于后续领域、应用、API、仓储、AI和实时行为测试。目前没有测试用例，不能报告后端或产品测试已通过。

T00.3将先审阅`outputs/twoworlds/backend/tests/test_platform.py`，按当前会话、动作参数、回执和玩法契约修订测试意图，再迁入本目录。当前不把旧六步谜题测试直接复制进来，也不为了显示绿色结果添加仅检查常量的测试。

pytest采用importlib导入方式；测试依赖`uv sync`安装后的`twoworlds`包，不通过`pythonpath = ["."]`临时掩盖包布局问题。
