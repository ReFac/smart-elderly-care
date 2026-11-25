# DeerFlow 主对话与专门任务

[文档导航](../../docs/README.md) · [English](README.en.md)

健康助理在同一个 DeerFlow 框架内回答员工、委派任务和读取已授权的工具。院务服务掌管账号权限、机构密钥、操作确认及用量账本。两边通过私有管道交换当前任务需要的资料。发布版本为 ByteDance DeerFlow v2.2.0，harness 和 extension API 均从同一提交构建。[官方发布](https://github.com/bytedance/deer-flow/releases/tag/v2.2.0) · [固定源码](https://github.com/bytedance/deer-flow/tree/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a)

| 工作 | 如何执行 |
| --- | --- |
| 员工对话、语音转写后的提问 | 主图收到员工的问题，按当前账号可见范围选择工具、读取社区 Skill，或把任务交给专门 Agent。实际改动需由有权员工确认。 |
| MCP 与 Skills | 宿主先审核可用的服务、工具和资料，DeerFlow 子进程再读取相应的 Skill 或通过 MCP 会话调用机构准许的只读工具。 |
| 文书、在院健康复核与生活简报 | 证据图通过 `read_authorized_evidence` 读取这次作业的摘录，请院务服务调用机构模型。工作图核对输出的原文行号；生活简报另核对日期分组与遗漏。作业编号关联经办人、按页计量的 OCR 和模型费用。 |
| 草稿、签认与家属投递 | 等候处理的文书与巡查作业留在加密库内。收到草稿后，院务服务重查状态、订阅和权限，再办理签认或投递并留下回执。 |

## 安装

Linux 主机需有 Git 和 Python 3.12 或以上版本。在项目根目录建立专用环境。下例假定 `python3` 符合版本要求。如果院务服务仍用 Python 3.11，可用单独安装的较新解释器建立这个 venv。

```bash
python3 -m venv .local/deerflow-venv
.local/deerflow-venv/bin/python -m pip install -r deploy/deerflow/requirements.txt
.local/deerflow-venv/bin/python -m pip install --no-deps -r deploy/deerflow/sdk.txt
python3 -c 'from platform_core.agents.deerflow_worker import installation; print(installation())'
python3 tests/run.py -p test_deerflow_worker.py
```

`requirements.txt` 记录在 Linux / CPython 3.14 的干净环境中验证过的依赖版本。该环境只运行嵌入式图；上游完整 Gateway 的依赖需要另行安装。两个官方包由 `sdk.txt` 固定到同一提交。启动探针检查包版本、源码提交与子目录、运行依赖和必需模块。正常时会看到 `ready: True`、harness `2.2.0`。也可用 `NH_DEERFLOW_PYTHON` 指定解释器的绝对路径。安装后重启服务，Owner 可在部署控制台查看状态。

`NH_DEERFLOW_BACKEND` 的有效值为 `deerflow`，默认使用此值。旧配置若显式指定了 `direct`，请在迁移时修改。环境未就绪时，助理报告当前状态，待处理任务按其重试策略继续排队；员工仍可手工整理已保存的原件。两个工作进程使用私有临时目录，院内密钥和长期资料仍由主服务保管。[主对话及工具](conversation.py) · [证据图](worker.py)

## 从已审核的经验提出建议

在健康助理中打开「改进回答」，或从机构设置的「平台 AI 套餐 → 管理助理写作规则」进入。选择院区、主题，点击「从审核记录提议」，即可从该范围内最近 40 条已采纳或已驳回的建议生成草稿。普通员工只用自己的审核历史，审核员可使用其具有审核权的院区记录；云模型收到的是栏目顺序、审核结果和计数。没有可用的审核记录时，员工可先手工提出调整，待审核后使用经验生成。

预览会显示用例和官方 SDK 对候选 Skill 的检查回执，含 DeerFlow 版本和内容摘要。提交形成待审建议，有权员工批准后才作为本院区的新版本使用。可驳回建议，也可通过审核回退到历史版本。已发布的规则储存在机构加密库中。

嵌入式部署调用官方 `validate_candidate` 和 Skill Review 分析器检查候选内容。上游 Gateway 另有 `stage`、`check`、`commit` 接口，可按已完成的运行记录发布自定义 Skill；它要求单台 POSIX 主机、本机共享的技能目录、持久数据库、数据库保存的运行事件，以及已启用的安全扫描模型。此处未启动该 Gateway；个人对话和病历也不会自动写入宿主共享记忆。[上游 Skill Evolution 交付条件](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/docs/skill-evolution-host.md)

预览、提交、批准或恢复版本时，嵌入式检查都会运行。提交后的「审核与记录 → 查看审核依据」可以打开候选原文、原版本和官方静态检查报告（`deerflow.skill-review.report.v1`）。从既往决定生成的建议还带有匿名计数。待审件不能被对话和定时任务读取；批准后，两者使用该院区这一个版本的 Skill 正文。员工可以比对内容摘要。这里的发布是院内写作规则的人工发布，静态报告本身不代表医疗效果或行为验证。

## 可选的 Gateway 同步

需要把已审核规则发布为 DeerFlow Gateway 里的用户自定义 Skill 时，可安装随库的 [Gateway 扩展](gateway_extension.py)。每家机构各自部署。工作台和 Gateway 必须在同一台 POSIX 主机，Gateway 使用持久数据库，并将 `run_events.backend` 设为 `db`。对 SQLite 使用单一 Gateway 进程；技能文件放在本机文件系统。照上游指南启用静态扫描、配置并验证有权限调用的安全扫描模型。扫描会将候选技能文本发送给该模型。[上游启用条件](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/docs/skill-evolution-host.md#enable-deliberately)

1. 在机构服务环境设定 `NH_EXPERIENCE_GATEWAY=1` 后重启。为每个接入院区分配独立的 Gateway 账号，在该账号下创建并启用相应的自定义 Skill，例如 `careops-meals`。其目录只允许一个不可执行的 `SKILL.md`，frontmatter 至少含同名 `name` 和 `description`。
2. 让 Gateway 的 Python 解释器能从只读目录导入 `gateway_extension.py`。将下面的片段并入 Gateway 的 `config.yaml`，将占位账号、院区和端口改为实际值。需要发布其他主题时，可在同一条配置的目标名单中加入 `careops-handover`、`careops-visit` 或 `careops-observations`。重启 Gateway，并在插件设置启用 `careops.reviewed-skills`。
3. 具有该院区规则审核权限的员工，在已登录的工作台会话向 `POST /api/assistant/learning/gateway-ticket` 提交 `{"campusId":"campus-main","topic":"meals","version":1,"gatewayOwner":"gateway-care-lead","confirm":true}`。版本号取本院区当前已批准版本。返回值的 `ticket` 有效 5 分钟；员工退出登录、失去权限、发布新版本、重新签发或凭证过期后，旧凭证立即失效。该凭证只允许接收一份已审核写作规则。它不包含员工登录口令。
4. 在已登录的目标 Gateway 浏览器会话，通过 `POST /api/plugins/careops.reviewed-skills/actions/stage` 提交 `ticket`、`threadId`、`runId`。对话和运行必须真实存在，来自该账号已成功结束、证据已封存的 `lead_agent` 交互运行。扩展比对候选字节并请 Gateway 检查，返回 `proposalId`、`decision`、`candidateHash` 和工作台摘要。两种摘要对应不同包格式。
5. 核对后以同一账号在 `POST /api/plugins/careops.reviewed-skills/actions/publish` 提交 `ticket`、`proposalId` 和 `confirm: true`。超过 5 分钟可向工作台重新领取当前版本的凭证。发布前再次检查员工资格、机构当前版本和扫描结果。成功时返回 `operationId`、`publication`、`views` 和 `generation`；重复提交同一请求会查回原操作。若出现未完成状态，按上游同一操作号恢复。[Gateway 恢复说明](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/docs/skill-evolution-host.md#publication-recovery-and-rollback)

```yaml
plugins:
  - name: careops-reviewed-skills
    use: gateway_extension:install
    config:
      workspace_port: 8765
      owner_campuses: {gateway-care-lead: campus-main}
    host_access:
      evidence:
        owners: [gateway-care-lead]
      skill_mutations:
        owners: [gateway-care-lead]
        operations: [stage, check, commit]
        trigger_agents: [lead_agent]
        target_skills: [careops-meals]
        topology: single_host_local
```

Gateway 只接受其宿主认证过的人工浏览器会话，此扩展没有向模型注册任何发表工具。工作台默认不开启同步。集成测试使用临时 SQLite 和真实 Gateway 宿主能力，以模拟扫描结论验证发布和幂等；正式交付时还要用机构自己的安全扫描账号与上线配置验收。
