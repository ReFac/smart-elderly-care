# 机构只读 A2A 服务

[文档导航](README.md) · [English](en/agent-protocol.md)

合作方的智能体可用 A2A 1.0 JSON-RPC 查询授权范围内的空床和今日照护工单。两项查询都从当前院区台账取数。调用方会收到汇总数量和任务编号，可以凭编号再次取回结果。公开能力卡说明接口和认证方式。

| 操作 | 路径或方法 | 调用结果 |
| --- | --- | --- |
| 发现能力 | `GET /.well-known/agent-card.json` | 服务地址、两项技能和账号会话认证方式 |
| 提交查询 | `POST /api/a2a`，`SendMessage` | 返回已完成的任务和带时间戳的文本结果 |
| 查询任务 | `GetTask` | 仅任务所属账号可读取，服务重启后可继续查询 |
| 取消 | `CancelTask` | 这两项查询同步完成，已完成任务返回 `-32002` |

在运行服务的 Python 环境执行 `python -m pip install -r requirements-a2a.txt`，然后重启。生产环境应设置机构 HTTPS 域名。如果未安装这个可选 SDK，查询入口会返回 503。

对接方应使用专用员工账号，通过 `POST /api/auth/login` 登录，随后用会话 Cookie 发起查询。消息正文不得包含密码或会话。账号需要健康助理权限和对应业务页权限，院区及责任范围由工作台确定。公共访客和家属账号无法调用。公开卡不包含机构、员工和长辈信息。

消息类型为 `text/plain`。发送 `bed-availability` 或“床位概况”，可获取可见床位总数、空床数、已占用数。发送 `today-care-work` 或“今日照护工单”，可查看今天每种状态各有多少工单。服务不接收附件、网页地址、租户、病历、外部回调或业务写入指令。

```json
{"jsonrpc":"2.0","id":"read-123","method":"SendMessage","params":{"message":{"messageId":"schedule-123","role":"ROLE_USER","parts":[{"text":"today-care-work"}]}}}
```

`result.task.id` 是取回结果所需的任务编号。重试同一条消息时请保留 `messageId`。同一账号发起另一项查询时需换用新的请求编号和消息编号，否则服务会拒绝请求。服务每次读取前都重新核对机构、账号、权限和院区分配。若授权范围已变，请发送新消息，获取当前范围的结果。

```json
{"jsonrpc":"2.0","id":"get-123","method":"GetTask","params":{"id":"替换为任务编号"}}
```

使用 `python tests/run.py -p test_agent_protocol.py` 验证官方客户端能否发现服务、登录、发送消息、取回结果和退出，以及并发重试、编号冲突、重启恢复和授权变更。工作台提供同步查询，公开卡未声明流式传输或异步推送。[A2A 1.0 规范](https://a2a-protocol.org/v1.0.0/specification/) · [官方 Python SDK](https://github.com/a2aproject/a2a-python)
