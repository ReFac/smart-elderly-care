# 健康助理的工具与技能

[文档导航](README.md)

员工从「健康助理」进入对话。问「帮我填这位长辈的个人信息，一张照片可以吗」可以直接取得上传入口。确认资料类型和长辈之后，打开带预填值的登记表。相同姓名按床位核对，识别不清或有冲突的值留给员工复核。保存按钮在业务表单底部。

## 登记工作表

在健康助理下载登记表模板，或从识别结果下载预填工作表。在 Excel、WPS 或 LibreOffice 中编辑后，可以上传 XLSX 或 Excel 97–2003 的 XLS。第一行填写表头，一行一人。如果有多张工作表，把登记页命名为「长辈登记」或「Resident registration」。工作台支持姓名、出生日期、联系电话、常用语言、婚姻状况、文化程度、原职业、籍贯、出生地和现住址。选择一行并核对姓名后，可补充授权范围内的档案或新建。公式字段、无法确认的选项和地址会提示核对。上传和下载工作表均不提交档案。

## 部署

在运行服务的 Python 环境安装依赖后，重启服务。

```sh
python3 -m pip install -r requirements-harness.txt
```

Owner 可在「机构设置 → AI 套餐与识别服务 → 查看助理工具与技能」查看已配置的聊天工具与工作方法。默认提供时间查询、时区换算和回顾时段计算，可试问「现在多伦多几点，和北京时间相差多久」。表格导出使用独立的 Excel MCP 进程，只能写入此次请求的临时目录。导出完成后回收临时文件。聊天和工具答复按员工记录实际模型用量。[官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) · [社区时间服务](https://github.com/modelcontextprotocol/servers/tree/main/src/time) · [Excel MCP](https://github.com/haris-musa/excel-mcp-server)

## 接入新的扩展

复制示例配置，设置服务环境变量 `NH_MCP_CONFIG` 指向实际文件。配置由运行服务的用户或 root 持有，限制他人写入。支持 stdio 和 Streamable HTTP。每个工具配置服务端工具名、所需岗位权限、文字说明、关键词及允许的参数。非本机 HTTP 服务须使用 HTTPS 并显式声明机构信任。主聊天只开放经运营方配置且服务端声明为只读的工具。路径、凭据和自由文本不作为外发参数。岗位或区域权限变化时，正在处理的请求会重新校验。[配置示例](examples/workspace-mcp.json)

将审核过的技能放入 `NH_AGENT_SKILL_DIRS` 指向的目录，目录下每个技能保留原有的 `SKILL.md` 和 Markdown 示例。模型可按需读取指导和示例，技能文件不能授予额外业务权限。工作台内置社区沟通写作和表格整理方法，并提供长辈档案办理说明。随附许可证和上游版本见项目清单。[技能来源](../skills/UPSTREAM.md) · [Agent Skills 格式](https://agentskills.io/specification)
