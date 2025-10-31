"""
droidrun.com 子包初始化

该子包承载通信与测试脚本，便于通过 `droidrun.com.*` 引用：
- `com.py`：通信与会话抽象（服务端与客户端工具）；
- `testServer.py`：测试侧动作决策逻辑；
- `testClient.py`：测试侧客户端通信序列；
- `test.py`：测试编排主程序。
"""

# 对外常用导出（可选）
from .com import ComServer, ComClient, ClientSession, log, Message_types