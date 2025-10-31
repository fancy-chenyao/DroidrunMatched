# com 通信模块接口文档

本文件总结 `test/com.py` 中的核心接口、输入与输出格式，便于在上层进行调用与联调。模块同时兼容旧格式（首字节类型 `I/X/S/A/E/G`）与简化版 JSON 的线协议；服务端侧将原始消息进行“预处理”，并返回标准化结构，上层（如 `testServer.py`）再基于预处理结果进行动作决策。

---

## 0. 消息类型常量（Message_types）
| 常量名 | 字面值 | 说明 |
|--------|--------|------|
| `Message_types.instruction` | `"instruction"` | 指令消息类型标识 |
| `Message_types.xml` | `"xml"` | XML 消息类型标识 |
| `Message_types.screenshot` | `"screenshot"` | 截图消息类型标识 |
| `Message_types.qa` | `"qa"` | QA 文本消息类型标识 |
| `Message_types.error` | `"error"` | 错误消息类型标识 |
| `Message_types.get_actions` | `"get_actions"` | 获取动作请求类型标识 |
| `Message_types.action` | `"action"` | 服务端下发动作的消息类型标识 |

说明：
- 常量类定义位置：`droidrun/com/com.py` 第 25 行处 `class Message_types:`；集中收敛所有协议中的 `messageType` 取值，避免在代码中使用魔法字符串。
- 使用方式：
  - 包内：`from .com import Message_types`
  - 包外：`from droidrun.com import Message_types`
- 示例：
  - 分发判断：`if mtype == Message_types.error: ...`
  - 构造负载：`{"messageType": Message_types.action, "action": {...}}`

---

## 1. 服务连接类函数
| 函数名 | 函数作用 | 输入参数 | 输出参数 | 备注 |
|--------|----------|----------|----------|------|
| `ComServer.__init__` | 初始化服务端实例 | `host`：绑定地址（可选，字符串，默认`"0.0.0.0"`）<br>`port`：端口（可选，数字，默认`6666`）<br>`buffer_size`：接收缓冲区（可选，数字，默认`4096`） | 无 | 仅构造对象，未开始监听 |
| `ComServer.start` | 启动服务端监听与接收线程 | 无 | 无 | 绑定地址端口并启动接入循环 |
| `ComServer.stop` | 停止服务端并释放会话资源 | 无 | 无 | 关闭监听套接字并关闭所有会话 |
| `ComClient.__init__` | 初始化客户端并建立 TCP 连接 | `host`：服务端地址（必填，字符串）<br>`port`：服务端端口（必填，数字） | 无 | 构造时即连接到服务端 |
| `ComClient.close` | 关闭客户端连接 | 无 | 无 | 释放 TCP 套接字 |

---

## 2. 发送指令类函数
| 函数名 | 函数作用 | 输入参数 | 输出参数 | 备注 |
|--------|----------|----------|----------|------|
| `ComClient.send_instruction` | 发送指令（旧格式 `I`） | `text`：指令文本（必填，字符串） | 无 | 线协议：`b"I" + text + "\n"` |
| `ComClient.send_xml` | 发送 XML（旧格式 `X`） | `xml_text`：XML文本（必填，字符串） | 无 | 线协议：`b"X" + len + "\n" + body` |
| `ComClient.send_screenshot` | 发送截图（旧格式 `S`） | `content`：图像二进制（必填，字节） | 无 | 线协议：`b"S" + len + "\n" + body` |
| `ComClient.send_error` | 发送错误（旧格式 `E`） | `error_text`：错误文本（必填，字符串） | 无 | 线协议：`b"E" + len + "\n" + body` |
| `ComClient.request_actions` | 请求动作列表（旧格式 `G`） | 无 | 无 | 线协议：`b"G"` |
| `ComClient.send_json` | 发送简化 JSON | `payload`：JSON对象（必填，字典） | 无 | 线协议：`b"J" + len + "\n" + json_bytes` |

---

## 3. 接收与预处理类函数
| 函数名 | 函数作用 | 输入参数 | 输出参数 | 备注 |
|--------|----------|----------|----------|------|
| `ComClient.receive_one` | 接收一条服务端消息 | `timeout`：超时（可选，秒，默认`1.0`） | `dict`或`None`：解析后的消息 | 支持接收 JSON 格式消息；若旧格式入站，尝试转为 JSON，否则返回原始文本 |
| `ComServer._receive_message` | 服务端接收并解析一条消息 | `client_file`：文件对象（必填） | `dict`或`None`：解析后的消息 | 自动兼容旧格式（`I/X/S/A/E/G`）与简化 JSON |
| `ComServer._receive_legacy_message` | 解析旧格式消息 | `client_file`（必填）<br>`type_char`：类型（必填，`"I"/"X"/"S"/"A"/"E"/"G"`） | `dict`或`None` | 返回示例：<br>• `I`→`{"messageType":"instruction","instruction":str}`<br>• `X`→`{"messageType":"xml","xml":str}`<br>• `S`→`{"messageType":"screenshot","screenshot":bytes}`<br>• `A`→`{"messageType":"qa","qa":str}`<br>• `E`→`{"messageType":"error","error":str}`<br>• `G`→`{"messageType":"get_actions"}` |
| `ComServer._receive_json_message` | 解析简化 JSON 消息 | `client_file`（必填）<br>`type_char`：首字节占位（必填） | `dict`或`None` | 线协议：占位字节 + 长度行 + JSON体 |
| `ComServer._dispatch_message` | 将原始消息分发到预处理函数并返回结果 | `session`：会话（必填，`ClientSession`）<br>`message`：原始消息（必填，字典） | `dict`或`None`：预处理后的消息 | 根据 `messageType` 调用 `_handle_*` 并返回结构化结果 |
| `ComServer._handle_instruction` | 指令预处理 | `session`（必填）<br>`message`（必填） | `dict`：`{"messageType":"instruction","processed":{"instruction_text":str,"session_id":str}}` | 仅预处理，不执行动作 |
| `ComServer._handle_xml` | XML预处理 | `session`（必填）<br>`message`（必填） | `dict`：`{"messageType":"xml","processed":{"xml_content":str,"xml_length":int,"session_id":str}}` | 仅预处理，不执行动作 |
| `ComServer._handle_screenshot` | 截图预处理 | `session`（必填）<br>`message`（必填） | `dict`：`{"messageType":"screenshot","processed":{"screenshot_data":bytes,"screenshot_length":int,"session_id":str}}` | 仅预处理，不执行动作 |
| `ComServer._handle_qa` | QA预处理 | `session`（必填）<br>`message`（必填） | `dict`：`{"messageType":"qa","processed":{"qa_text":str,"session_id":str}}` | 仅预处理，不执行动作 |
| `ComServer._handle_error` | 错误预处理 | `session`（必填）<br>`message`（必填） | `dict`：`{"messageType":"error","processed":{"error_text":str,"session_id":str}}` | 仅预处理，不执行动作 |
| `ComServer._handle_get_actions` | 获取动作请求预处理 | `session`（必填）<br>`message`（必填） | `dict`：`{"messageType":"get_actions","processed":{"request_type":"get_actions","session_id":str}}` | 仅预处理，不执行动作 |
| `ComServer._on_message_processed` | 预处理完成后的回调（可覆写） | `session`（必填）<br>`processed_message`（必填，字典） | 无 | 基类默认仅记录日志；测试侧在 `testServer.py` 覆写并执行动作决策 |

---

## 4. 发送动作类函数
| 函数名 | 函数作用 | 输入参数 | 输出参数 | 备注 |
|--------|----------|----------|----------|------|
| `ComServer.send_action` | 服务端向指定会话下发动作 | `session`：会话（必填）<br>`action`：动作（必填，字典，如`{"type":"tap","x":100,"y":200}`） | 无 | 线协议：JSON；负载为 `{"messageType":"action","action":{...}}` |
| `ComServer._send_json` | 底层发送 JSON | `sock`：套接字（必填）<br>`payload`：负载（必填，字典） | 无 | 线协议：`b"J" + len + "\n" + body`，内部供 `send_action` 等使用 |

---

## 5. 会话管理类函数
| 函数名 | 函数作用 | 输入参数 | 输出参数 | 备注 |
|--------|----------|----------|----------|------|
| `SessionManager.create_session` | 创建新会话 | `client_socket`（必填）<br>`client_address`（必填，元组） | `ClientSession` | 内部加锁并登记会话 |
| `SessionManager.get_session` | 获取会话（并刷新活跃状态） | `session_id`（必填，字符串） | `ClientSession`或`None` | 过期则移除并返回`None` |
| `SessionManager.get_session_by_socket` | 通过套接字查找会话 | `client_socket`（必填） | `ClientSession`或`None` | 查到即刷新活跃状态 |
| `SessionManager.remove_session` | 移除会话并关闭资源 | `session_id`（必填，字符串） | `bool` | 找到并移除返回`True` |
| `SessionManager.get_active_sessions` | 获取所有活跃会话 | 无 | `Dict[str, ClientSession]` | 同步清理过期会话 |
| `SessionManager.shutdown` | 关闭管理器与所有会话 | 无 | 无 | 停止清理线程并清空会话 |
| `ClientSession.update_activity` | 更新会话活跃状态 | 无 | 无 | 刷新心跳时间并初始化预缓冲 |
| `ClientSession.is_expired` | 判断是否过期 | `timeout_minutes`（可选，默认`30`） | `bool` | 超过阈值视为过期 |
| `ClientSession.close` | 关闭会话套接字 | 无 | 无 | 释放底层连接 |

---

### 线协议说明（简述）
- 旧格式：首字节消息类型（`I/X/S/A/E/G`）+ 按类型约定的长度与载荷。
- 简化 JSON：占位首字节（任意非上述类型）+ `长度\n` + JSON 文本。
- 服务端下发动作统一使用简化 JSON，负载形如：
```json
{
  "messageType": "action",
  "action": { "type": "ack_instruction", "text": "..." }
}
```