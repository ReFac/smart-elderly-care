# DeerFlow 2.0 文书与巡查任务

[文档导航](../../docs/README.md) · [English](README.en.md)

此进程运行 ByteDance 官方 DeerFlow v2.0.0 的 `create_deerflow_agent`。院务服务启动独立 Python 解释器，用私有管道交给它当前任务已获准读取的一组证据。在住长辈的健康复核与生活简报、员工上传的就诊资料使用同一个进程，逐项建立新图。进程在收到第一项任务时启动。已排队的文书和巡查保存在机构加密库中。[官方 v2.0.0 源码](https://github.com/bytedance/deer-flow/tree/7e7f0410797693cf882594555ba414e0361d4c6f)

| 工作 | 执行位置 |
| --- | --- |
| 网页聊天、语音转写后的提问、日常查询 | Pi 帮员工对话并提供操作入口。 |
| 核对长辈、院区、访问资格，保存原件、申请 OCR | 院务服务从当前会话或有效作业读取权限。OCR 按页计量，识别回执沿用平台的去重规则。 |
| 读取一次任务的证据、整理一份草稿和校验引用 | DeerFlow 的图通过 `read_authorized_evidence` 工具读取本次摘录。其模型通过院务服务调用机构配置的云端模型，得到字段对应的原文行号或简报分组。图核对引用范围，生活简报同时检查同日分组与完整性。 |
| 将草稿交给员工、办理签认或向家属投递 | 院务服务重新核对状态，处理员工签认、审计、订阅与去重。 |

## 安装

在 Linux 仓库根目录准备 Git 和 Python 3.12 或更高版本。以下使用专用 venv 安装工作进程。宿主架构支持的 Python 版本仍以院务服务部署说明为准。专用进程只需证据图实际使用的依赖；`--no-deps` 保留上一步的运行依赖，避免引入上游全套网关、文件解析器和其他可选服务。

```bash
python3 -m venv .local/deerflow-venv
.local/deerflow-venv/bin/python -m pip install -r deploy/deerflow/requirements.txt
.local/deerflow-venv/bin/python -m pip install --no-deps -r deploy/deerflow/sdk.txt
python3 tests/run.py -p test_deerflow_worker.py
```

`sdk.txt` 固定至 v2.0.0 发布提交。院务服务优先使用 `.local/deerflow-venv/bin/python`，也可通过 `NH_DEERFLOW_PYTHON` 指定本机独立环境的绝对解释器路径。安装或切换解释器后重启院务服务。

[工作进程](worker.py) 隔离运行配置、技能搜索目录和临时目录。密钥与个人数据的永久存储由院务服务持有。工作图只开放一个只读工具，使用本次请求的来源与已审核流程指引。借助相同任务编号可以在用量页核对经办员工、平台 OCR 和模型支出。

默认值为 `NH_DEERFLOW_BACKEND=deerflow`。依赖缺失时，文书任务报告未就绪，巡查作业等待重试。机构需要紧急切回原直连模型整理时，可在部署环境显式设为 `direct` 并重启。这些调用的运行时计为平台；恢复默认设置后新请求使用 DeerFlow。已留存原件仍可人工整理。
