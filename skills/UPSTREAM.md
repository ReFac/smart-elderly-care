# 随工作台分发的社区技能

工作台用 `internal-comms` 起草院内通知、周报、常见问题回复和管理简报。目录里的 `SKILL.md`、四份 Markdown 示例及 Apache-2.0 许可证取自 Anthropic 的开源技能库。示例已去掉行尾空格，其余上游内容照原样保留。[上游固定版本](https://github.com/anthropics/skills/tree/e4bb5d960d87126ff3b3a8af1a104b7db67560ba/skills/internal-comms)

要加载运营方审核过的社区技能，在服务器上设置 `NH_AGENT_SKILL_DIRS`，例如 `NH_AGENT_SKILL_DIRS=/srv/care/approved-skills`。Linux 上的多个绝对路径用冒号分隔。每个根目录下按 `技能名/SKILL.md` 存放，目录名与 YAML 的 `name` 必须一致。工作台默认也会读取仓库内的 `skills/`。遇到同名技能时先用内置版本，再按配置目录的先后顺序选择。[开放格式](https://agentskills.io/specification)

工作台先列出技能名称和用途，DeepSeek 选定技能后才读取正文。技能可引用 `references/` 和 `examples/` 下的 Markdown 文件，工具会列出可读的文件名。对话运行器只能读取文档。如需运行脚本、执行命令或发布内容，工作台须另行提供相应功能，并按账号授权。

员工须先有健康助理权限。要让技能仅供有入住管理权限的员工使用，可在 YAML 的 `metadata` 中填写 `workspace-permission: intake`。社区技能声明的 `allowed-tools` 不会给账号增加工具权限。内部沟通技能生成通知草稿，发送前仍由员工核对。

工作台的 `xlsx` 改编自 Nous Research 以 MIT 许可发布的 Hermes XLSX 技能。它沿用上游「Procedure」「Pitfalls」「Verification」中检查工作表结构和日期类型、逐项比对值、重新读取修改范围的办法，并增加院内的 OCR、证件和人工确认步骤。复用范围限于 Markdown 中的工作方法，实际读写 Excel 文件使用工作台已经开通的表格工具。MIT 许可证随附在 `xlsx/LICENSE.txt`。[上游固定版本](https://github.com/NousResearch/hermes-agent/blob/dc82bec3bd4d2d63e25c1854f5f2b081f05aad38/skills/productivity/xlsx/SKILL.md)
