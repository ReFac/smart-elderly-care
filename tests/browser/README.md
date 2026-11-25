# 中文浏览器回归

在仓库根目录运行下表中的脚本。每次浏览器验收使用临时的简体中文（`zh-CN`）机构和虚构账号。Chromium 脚本需要项目的存储依赖、`websocket-client` 和可监听的本地回环端口。已安装的 Chromium、Chrome 或 Edge 会被自动发现，也可用 `BROWSER_BIN` 指向本机可执行文件。

| 要核对什么 | 运行哪个入口 |
| --- | --- |
| 桌面目录、固定页签、刷新后表单状态 | `python3 tests/browser/desktop_workspace.py` |
| Owner、接待、财务、护士、亲属和访客的实际菜单及授权变化 | `python3 tests/browser/workspace_roles.py` |
| 未登录参观、Roomtour、自愿回电、访客注册 | `python3 tests/browser/public_visitors.py` |
| 从对话提交就诊原件，在 DeerFlow 整理期间继续提问，最后核对签认人与任务用量 | `python3 tests/browser/assistant_visit_delegation.py` |
| 员工提交答复纠正、授权复核、发布与回退 | `python3 tests/browser/agent_learning.py` |
| 定时生活简报与健康复核独立排程、证据及读者权限 | `python3 tests/browser/resident_specialists.py` |
| 桌面及窄屏的 WebKit 登录和工作台导航 | `python3 tests/browser/webkit_workspace.py` |

先执行 `export NH_DEPLOYMENT_LANGUAGE=zh-CN`，再选择与改动相应的入口。WebKit 环境与真机复核步骤见客户端说明。此目录也保留其他部署版本的脚本和供浏览器载入的 HTML 场景，请按入口运行。报告写明实跑场景、设备或模拟窗口，以及待现场复核的部分。[客户端验收说明](../../docs/client-compatibility.md) · [仓库测试约定](../../AGENTS.md)
