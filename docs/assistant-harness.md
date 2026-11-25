# 健康助理的工具与技能

[文档导航](README.md)

打开「健康助理」，问「帮我填这位长辈的个人信息，一张照片可以吗」。点击回答中的按钮上传照片，确认资料类型和长辈，再打开预填的登记表。如果有同名长辈，先核对床位。看不清或互相矛盾的字段由员工核对，最后在表单底部保存。

## 登记工作表

在健康助理下载登记表模板，或从识别结果下载预填工作表。在 Excel、WPS 或 LibreOffice 中编辑后，可以上传 XLSX 或 Excel 97–2003 的 XLS。把字段名放在第一行，从第二行起每行填一位长辈。如果有多张工作表，把登记页命名为「长辈登记」或「Resident registration」。工作台支持姓名、出生日期、联系电话、常用语言、婚姻状况、文化程度、原职业、籍贯、出生地和现住址。选中一行、核对姓名后，可新建档案，也可补充有权编辑的档案。遇到公式、无法识别的选项或地址，工作台会提示人工核对。档案由员工在业务表单中提交，上传或下载工作表都不会改变档案。

## 部署

在运行服务的 Python 环境安装依赖后，重启服务。

```sh
python3 -m pip install -r requirements-harness.txt
```

Owner 可在「机构设置 → AI 套餐与识别服务 → 查看助理工具与技能」查看助理已启用的工具和技能。默认提供时间查询、时区换算和回顾时段计算，可试问「现在多伦多几点，和北京时间相差多久」。表格导出使用独立的 Excel MCP 进程，只能写入此次请求的临时目录。导出完成后回收临时文件。聊天和工具答复按员工记录实际模型用量。[官方 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) · [社区时间服务](https://github.com/modelcontextprotocol/servers/tree/main/src/time) · [Excel MCP](https://github.com/haris-musa/excel-mcp-server)

## 接入新的扩展

复制示例配置文件，再将服务环境变量 `NH_MCP_CONFIG` 指向配置文件的实际位置。文件所有者须为服务账号或 root，同时要限制其他账号的写入权限。支持 stdio 和 Streamable HTTP。每个工具配置服务端工具名、所需岗位权限、文字说明、关键词及允许的参数。非本机 HTTP 服务须使用 HTTPS 并显式声明机构信任。主聊天只开放经运营方配置且服务端声明为只读的工具。路径、凭据和自由文本不作为外发参数。岗位或区域权限变化时，正在处理的请求会重新校验。[配置示例](examples/workspace-mcp.json)

将审核过的技能放入 `NH_AGENT_SKILL_DIRS` 指向的目录，目录下每个技能保留原有的 `SKILL.md` 和 Markdown 示例。模型可按需读取指导和示例，技能文件不能授予额外业务权限。工作台随附社区的沟通写作和表格整理技能，以及本项目的长辈档案办理说明。技能清单列出了上游版本和许可证。[技能来源](../skills/UPSTREAM.md) · [Agent Skills 格式](https://agentskills.io/specification)
