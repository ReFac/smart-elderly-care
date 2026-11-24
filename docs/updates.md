# 机构服务版本更新

Owner 打开「机构设置 → 平台更新」查看当前版本，检查新版和安装状态。先执行「下载并校验」，核对发布说明，再选择「备份并安装」。安装期间工作台会短时离线。更新前保护点可在「备份与恢复」查看，也可按现有流程核验和导出。

开启自动更新后，受托管的机构服务每天在设定的北京时间时段检查，默认 02:00 至 02:59。它会下载有可信签名且版本号更高的正式发布，校验后执行相同的备份和安装步骤。关闭自动更新后仍可手动操作。没有可信发布源或托管启动器时，页面显示实际部署状态。

## 启用机构端

安装现有 Python 依赖。由部署人员把发布公钥配置为服务账号可读的本机文件，并把更新清单地址配置为机构信任的 HTTPS 地址。

~~~bash
export NH_UPDATE_MANIFEST_URL=https://updates.example.org/ankang/latest.json
export NH_UPDATE_PUBLIC_KEY_FILE=/etc/ankang/release-signing.pub
python3 manage_updates.py run --db /srv/ankang/workspace.sqlite3 --port 8765
~~~

使用生产域名时保留原有 `--public-origin` 参数。每个机构资料库仅运行一个托管服务。部署为 systemd 等服务时同时管理启动器及其子进程。业务库用原有路径和密钥，平台运维密库、异地位置和部署凭据继续由原服务账号管理。

浏览器及通过 Electron 连接机构工作台的人将在同一网址使用新版。现有便携式 Electron 原生外壳使用操作系统的独立发行包。正式分发原生外壳时采用对应平台的签名安装方式。[Electron 自动更新支持范围](https://www.electronjs.org/docs/latest/api/auto-updater)

## 发布新版

在独立的发布主机用 Ed25519 私钥生成发布文件。生产私钥由发布方离线保管，安装机构持有对应公钥。以下命令假设私钥已经生成并处于专用目录。

~~~bash
python3 manage_updates.py build --version 0.2.1 --output ./release-0.2.1 --key-file /offline-signing/release.pem --notes "本次发布内容"
~~~

把 ZIP 程序包上传至配置的同一 HTTPS 路径，再发布 `latest.json`。每次改变发布包都使用新的版本号。清单签名覆盖产品、版本、包名、文件体积、SHA-256 与发布说明。安装前会再次核对签名与包摘要。发布包包含工作台资源和机构服务代码，系统级依赖仍由部署方预先提供。

## 时间点和失败回退

托管启动器停止旧服务并确认资料库已释放，再建立并隔离恢复核验完整 `.akbak` 时间点。快照包含该机构工作库中的全部已提交资料，包括数据库内的原件、护理及医疗记录。外部托管素材和平台运营密库沿用各自的保管与备份方式。

新版只有通过本机启动检查才对用户开放。校验、备份或启动失败时记录结果。若新版已触及数据库但没有通过启动检查，托管启动器会从刚保存的时间点恢复机构库，并重新启动原程序。成功和回退均保留更新前保护点供核查。

## Owner 接口

| 方法及路径 | 用途 |
| --- | --- |
| `GET /api/updates` | 读取版本、自动设置、候选版本、最近结果和保护点编号 |
| `POST /api/updates/check` | 用空 JSON 对象检查已配置的可信更新源 |
| `POST /api/updates/download` | 通过 `version` 下载并校验候选包 |
| `POST /api/updates/install` | 通过 `version` 确认更新前备份和托管安装 |
| `POST /api/updates/settings` | 通过布尔值 `automatic` 和整数 `hour` 设置自动检查安装时段 |
