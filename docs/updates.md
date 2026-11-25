# 机构服务版本更新

[文档导航](README.md)

Owner 在「机构设置 → 平台更新」可查看当前版本、新版和安装进度。手动升级时，先点「下载并校验」，看过发布说明后再点「备份并安装」。安装期间工作台会短时离线。更新前的保护点在「备份与恢复」里，可以核验和导出。

开启自动更新后，受托管的机构服务每天在设定的北京时间时段检查，默认 02:00 至 02:59。它会下载有可信签名且版本号更高的正式发布，校验后执行相同的备份和安装步骤。关闭自动更新后仍可手动操作。没有可信发布源或托管启动器时，页面显示实际部署状态。

## 启用机构端

安装现有 Python 依赖。由部署人员把发布公钥配置为服务账号可读的本机文件，并把更新清单地址配置为机构信任的 HTTPS 地址。

~~~bash
export NH_UPDATE_MANIFEST_URL=https://updates.example.org/eldercare/latest.json
export NH_UPDATE_PUBLIC_KEY_FILE=/etc/eldercare/release-signing.pub
python3 manage_updates.py run --db /srv/eldercare/workspace.sqlite3 --port 8765
~~~

使用生产域名时，沿用原有的 `--public-origin` 参数。同一机构资料库只运行一个托管服务。使用 systemd 等服务管理器时，要同时管理启动器和子进程。业务库沿用原路径和密钥，原服务账号继续管理平台运维密库、异地位置和部署凭据。

浏览器及通过 Electron 连接机构工作台的人将在同一网址使用新版。现有便携式 Electron 原生外壳使用操作系统的独立发行包。正式分发原生外壳时采用对应平台的签名安装方式。[Electron 自动更新支持范围](https://www.electronjs.org/docs/latest/api/auto-updater)

## 发布新版

在独立的发布主机用 Ed25519 私钥生成发布文件。生产私钥由发布方离线保管，安装机构持有对应公钥。以下命令假设私钥已经生成并处于专用目录。

~~~bash
python3 manage_updates.py build --version 0.2.1 --output ./release-0.2.1 --key-file /offline-signing/release.pem --notes "本次发布内容"
~~~

把 ZIP 程序包上传至配置的同一 HTTPS 路径，再发布 `latest.json`。每次改变发布包都使用新的版本号。清单签名覆盖产品、版本、包名、文件体积、SHA-256 与发布说明。安装前会再次核对签名与包摘要。发布包包含工作台资源和机构服务代码，系统级依赖仍由部署方预先提供。

### 随版更新 DeerFlow

签名包包含主对话和证据图、随库 Skill 和许可、默认 MCP 工具清单、运行配置及依赖锁。候选版启动前会用一轮虚构的中文问答测试主图，再启动证据图；这些自检不读取机构资料，也无需调用云模型。依赖版本匹配后，升级期间可以离线启动。

依赖有变化时，先给服务配置只读运行时目录 `NH_AGENT_RUNTIME_STORE`。在独立的发布源码目录运行以下命令，按锁指纹为该版本预装环境。示例中的 Python 需满足 DeerFlow 的版本要求，原版本的运行环境继续保留。[运行时安装说明](../deploy/deerflow/README.md)

~~~bash
export NH_AGENT_RUNTIME_STORE=/opt/care-runtimes
digest=$(cat deploy/deerflow/requirements.txt deploy/deerflow/sdk.txt | sha256sum | cut -d' ' -f1)
target="$NH_AGENT_RUNTIME_STORE/deerflow/$digest"
install -d -m 755 "$target"
install -m 644 deploy/deerflow/requirements.txt deploy/deerflow/sdk.txt "$target/"
python3 -m venv "$target/venv"
"$target/venv/bin/python" -m pip install -r "$target/requirements.txt"
"$target/venv/bin/python" -m pip install --no-deps -r "$target/sdk.txt"
~~~

### 从旧启动器迁移

旧托管启动器可能只允许上一代工作进程的签名文件，拒绝新包内的 DeerFlow 入口。首次迁移时，将经过机构运维核准的**新版完整源码和宿主依赖**放在独立只读目录，例如 `/opt/care-launcher`。在运维交付渠道核对提交号或制品签名。旧代码、已签名的历史发行目录和历史运行时继续保留，供回退使用。

沿用机构现有的 `NH_UPDATE_MANIFEST_URL` 和 `NH_UPDATE_PUBLIC_KEY_FILE`，下载新版清单及同目录程序包。在维护窗口先运行离线预检。它验证公钥签名、大小、摘要和允许解包的文件，然后清理临时目录，不访问业务库。

~~~bash
/opt/care-launcher/.venv/bin/python /opt/care-launcher/manage_updates.py verify-package --manifest /srv/care-release/latest.json
~~~

预检通过后，停止原托管服务，在同一系统服务中使用新版启动器，并传入原安装路径、数据库、端口和生产域名。以下是启动命令示例；使用 systemd 时替换原 `ExecStart`，保留原服务账号、密钥位置、运行时目录和环境文件，然后重新加载并启动同一个服务。

~~~bash
/opt/care-launcher/.venv/bin/python /opt/care-launcher/manage_updates.py run --install-root /opt/care-workspace --db /var/lib/care-workspace/institution.sqlite3 --initial-data empty --port 8765 --public-origin https://care.example.org
~~~

启动器会先运行原来选定的应用版本。Owner 再按「下载并校验 → 备份并安装」完成首次切换。后续更新继续由这个启动器托管；若候选版探针失败，它会恢复升级前的资料并从原来的代码目录重新启动。出现旧配置 `NH_DEERFLOW_BACKEND=direct` 时需先改为 `deerflow`；新版所有对话和专门任务都需要 DeerFlow。

## 时间点和失败回退

托管启动器先停止旧服务，确认资料库已释放，再创建完整的 `.akbak` 快照，并在隔离环境中恢复一次以核验它。快照收录机构工作库内所有已提交的资料，包括原件、护理记录和医疗记录。外部托管的素材和平台运营密库仍需各自保管、备份。

新版通过本机启动检查后才会对用户开放。若校验、备份或启动失败，系统会留下记录。若新版已访问数据库却未通过启动检查，启动器会用更新前刚保存的快照恢复机构库，然后重新启动旧版。升级成功或回退后，都可以查到这份保护点。

## Owner 接口

| 方法及路径 | 用途 |
| --- | --- |
| `GET /api/updates` | 读取版本、自动设置、候选版本、最近结果和保护点编号 |
| `POST /api/updates/check` | 用空 JSON 对象检查已配置的可信更新源 |
| `POST /api/updates/download` | 通过 `version` 下载并校验候选包 |
| `POST /api/updates/install` | 通过 `version` 确认更新前备份和托管安装 |
| `POST /api/updates/settings` | 通过布尔值 `automatic` 和整数 `hour` 设置自动检查安装时段 |
