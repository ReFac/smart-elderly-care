# 平台托管的 AI 套餐

安康医养平台把人工确认、房间搜索、档案与本地协作保留在机构工作区。云端套餐按机构单独开通，为授权员工提供一次短请求的 Agent 分派。现阶段以运营方核验收款后手动发放的 token 额度计量。

## 谁可以做什么

| 身份 | 职责 |
| --- | --- |
| 平台运营方 | 在平台控制的服务器保管供应商凭据，核实客户付款，按机构数据库发放、停用与对账。 |
| 机构总管理员 | 查看本院套餐的到期日、额度、已用量和在途预留量，给员工分配 Agent 和业务域权限。 |
| 获授权员工 | 在工作台选择云端规划。服务端根据其岗位权限计算可委派的业务域。 |
| 家属等其他账号 | 使用各自获授权的机构功能。 |

对外销售采用平台托管服务。每个客户对应独立机构数据库，客户使用浏览器、Electron 或手机入口。供应商密钥在平台后端，机构客户端只持有受限的登录会话。将整个后端、数据库管理员权限及密钥交由客户控制的私有化部署，应另行实施平台托管的计量网关。

## 开通与对账

1. 启动机构工作台，确定该机构实际使用的 SQLite 文件。
2. 在平台服务进程的部署环境中配置 `DEEPSEEK_API_KEY`。POSIX 主机也可以用 `NH_DEEPSEEK_KEY_FILE` 指定服务账号所有、权限为 0600 的普通文件。凭据使用服务端私密配置供给。默认模型为 `deepseek-flash`，仅平台部署参数 `NH_DEEPSEEK_MODEL` 可指定其他已验证标识。
3. 运营方核实付款及约定的服务期后，在该机构数据库上执行开通命令。下例的额度与日期均为示例，以实际订单为准。

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 grant --name "机构 AI 套餐" --tokens 100000 --expires 2026-12-31
python3 manage_plan.py --db .local/workspace.sqlite3 status
```

额度是当前服务期的 token 总量。有效期内再次执行 `grant` 将调整本期总额并保留原有用量。到期日按上海时区计算，含当日。到期后再次开通产生新服务期，旧用量保留在其原期。额度与供应商账户的人民币余额分别核算。

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 disable
python3 manage_plan.py --db .local/workspace.sqlite3 unsettled
python3 manage_plan.py --db .local/workspace.sqlite3 reconcile --actor ACCOUNT_ID --request REQUEST_ID --tokens CONFIRMED_USAGE
```

`disable` 停止本期的新请求。并发调用在发送前通过 SQLite 写事务预留额度，服务端在网络等待期间释放数据库写锁。成功响应按供应商返回的 `usage.total_tokens` 结算，未用的预留额度返还。已明确拒绝的请求释放预留。超时、用量缺失和发送阶段意外重启时保留相应额度。运营方可用 `unsettled` 获取账号、请求编号、时间和预留值，再根据供应商账单用 `reconcile` 录入实际用量。

## 会传给模型的内容

服务端从任务文本中匹配受控业务词，例如“工单”“交班”“库存”“欠费”。出站请求只含这些词及当前用户允许调用的业务域编号。姓名、身份证号、床位号、联系人、原始任务文本、业务表和医疗图片留在本地。没有匹配词时直接使用本地规划。

每次云端规划只请求一个 JSON 对象，输出上限 32 token。模型返回的专员编号应属于请求人当时获准的范围。保存费用后再次验证会话和当前岗位。相同账号与请求号的网络重试复用原有结果。错误或不可用状态转为可解释的本地降级，真实业务写入继续经过工作台原有的人工确认。

使用 DeepSeek Chat Completions JSON 输出与非思考模式。官方模型别名的实际版本由供应商维护。[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) · [JSON 输出](https://api-docs.deepseek.com/guides/json_mode/) · [思考模式开关](https://api-docs.deepseek.com/guides/thinking_mode/)

## 验收

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests -p test_provider.py -v
```

模拟供应商响应可重复检验云端开通、请求最小化、并发限额、幂等、撤权、供应商异常、续期和对账。真实凭据联调应使用虚构任务与平台批准的预算。供应商密钥、原始请求、数据库及本地环境文件由部署端保管。
