# 随工作台分发的社区技能

`internal-comms` 用于起草院内通知、周报、常见问题回复和管理简报。目录内的 `SKILL.md`、四份 Markdown 示例及 Apache-2.0 许可证均来自 Anthropic 的开源技能库，保留上游内容，已清理示例行尾空格。[上游固定版本](https://github.com/anthropics/skills/tree/e4bb5d960d87126ff3b3a8af1a104b7db67560ba/skills/internal-comms)

运营方可以将审核过的社区技能目录放进服务器配置的 `NH_AGENT_SKILL_DIRS`。在 Linux 上，多个绝对路径用冒号分隔。每个根目录下采用 `技能名/SKILL.md` 结构。技能名与 YAML 的 `name` 相同。工作台默认还读取本仓库的 `skills/`。同名时优先使用内置技能，再根据配置顺序选择。示例配置为 `NH_AGENT_SKILL_DIRS=/srv/care/approved-skills`。[开放格式](https://agentskills.io/specification)

工作台先提供技能名称和用途，DeepSeek 选中后才读取正文。技能还可以直接引用 `references/` 和 `examples/` 下的 Markdown 文件。工具返回可选资料文件名。对话运行器只提供文档阅读。脚本、命令和发布操作需要由相应的工作台能力另行提供并按账号授权。

岗位必须持有健康助理权限。在 YAML 的 `metadata` 下填写 `workspace-permission: intake`，即可将该技能再限定给具有入住管理权限的员工。社区格式中的 `allowed-tools` 声明不会给账号新增工具授权。内部沟通技能产出草稿，发送通知仍由员工核对。

`xlsx` 为 Nous Research 的 MIT 授权 Hermes XLSX 技能在本工作台的改编版。结合上游「Procedure」「Pitfalls」「Verification」保留工作表结构检查、日期类型、逐值对照和重新读取修改范围的做法，增加本机构的 OCR、证件和人工确认流程。协作范围限于 Markdown 工作方法，Excel 文件读写由工作台已开通的表格工具承担。MIT 许可证保存在 `xlsx/LICENSE.txt`。[上游固定版本](https://github.com/NousResearch/hermes-agent/blob/dc82bec3bd4d2d63e25c1854f5f2b081f05aad38/skills/productivity/xlsx/SKILL.md)
