# 机构完整快照与异地恢复

总管理员在「系统管理 → 机构设置 → 备份与恢复」查看本机恢复点、每个网盘的上传与回读结果。点击「立即创建快照」可在批量导入或交接前留下独立时间点。点击「验证恢复」会在私有临时目录解密、核验数据库页面和业务版本，结束后显示核验时间。生产切换由主机运维人员执行。[桌面验收画面（合成数据）](previews/encrypted-backups.jpg)

## 时间与覆盖范围

按北京时间每天 00:00、12:00 创建独立的全量快照。服务首次运行即创建当前时段的恢复点；主机错过一个或多个时段后，在重新上线时保存当时实际存在的数据。页面以实际捕获时间记录版本。每个时间点包含所有分院的账号与授权、员工资料、老人档案、护理及财务数据、识别与审核记录、已归档医疗图片、导入的环境原件和历史附件。时间点包含事务提交完成的版本。需要随时点恢复的环境图片请导入机构媒体库；外部素材网址只保留引用。[原件入库与存储格式](storage.md)

本机目录默认为工作库同目录下的 `workspace.sqlite3.snapshots/`。系统生成的 `.akbak` 是经过认证的密文。每个已连接的目标各有重试队列，收到完整远端文件、重新计算 SHA-256 并核对后才显示「异地已校验」。上传失败会保留本机恢复点，网络恢复后重试；管理员也可点「重试失败的备份」。网盘与本机的容量需要覆盖保留期内的全部完整副本。列表展示最近 50 个时间点，更早的文件仍在存储位置。

## 常驻定时任务

运行服务时自带备份工作线程。Linux 部署还应安装用户级 systemd 定时器，保证应用进程和浏览器退出后仍能执行。请以运行业务服务的同一账号运行。后台服务需要额外环境配置时，在安装命令末尾加 `--environment-file /受保护目录/backup.env`，通过同一套系统凭据管理向 Web 服务和定时任务供给存储密钥及网盘授权。

```bash
python3 manage_backups.py --db .local/workspace.sqlite3 run-due
python3 manage_backups.py --db .local/workspace.sqlite3 install-timer
systemctl --user list-timers 'ankang-backup-*'
```

部署管理员可用 `loginctl enable-linger 服务账号` 允许用户定时器在注销后继续运行。定时器在半日边界触发，并每隔 15 分钟检查积压任务。应用线程和主机定时器共享同一份幂等记录。其他系统可用原生任务计划程序每 15 分钟以同一账号运行上述 `run-due`，系统按固定时段去重。机器断电、磁盘写满或网盘持续不可达时，记录的最近成功时间反映实际恢复能力。最近快照显示「尚未接入位置」表示当前只有本机副本。

## 授权 iCloud、115、百度及其他异地存储

在部署端安装 rclone，试点已验证 v1.72.0。可将程序放在 `.local/backup-tools/rclone`、加入系统 PATH 或用 `NH_RCLONE_BIN` 指定。以服务账号执行 `rclone config`，为每个目标准备独立的专用目录与具有读写权限的账号。首次使用请在交互终端为 rclone 配置文件设置加密口令。定时任务通过服务账号的秘密管理器取得解锁口令，服务重启后也需要能非交互解锁。部署方保管账号认证及续期；总管理员在工作台选择哪些已授权位置可以接收本机构副本。[rclone 配置加密](https://rclone.org/commands/rclone_config_encryption/)

| 目标 | 部署与核对 |
| --- | --- |
| iCloud Drive | rclone 选择 `iclouddrive` 和 Drive 存储，用机构授权的 Apple 账号及双重认证完成登录。会话要求重新验证时，在部署机运行 `rclone config reconnect 远端名:`。[iCloud Drive 驱动](https://rclone.org/iclouddrive/) |
| 115 网盘 | 在机构私有 OpenList 上接入「115 开放平台」驱动，通过授权账号选择根目录，向备份服务开放该目录的 WebDAV 读写。每个销售部署使用机构各自获准的目录和授权，按 115 平台适用条款办理。[115 Open 接入](https://doc.oplist.org/guide/drivers/115_open) |
| 百度网盘 | 在机构私有 OpenList 中配置「百度网盘」，使用获准的应用及机构 OAuth 授权。配置通过网关代理下载，使超过 20 MiB 的副本也能由网关携带所需请求头回读。[百度网盘驱动](https://doc.oplist.org/guide/drivers/baidu) |
| 其他异地存储 | rclone 支持 WebDAV、SFTP、S3 等。为机构分配独立、可写且可完整回读的目录。首次接入可先用无个人信息的临时机构完成恢复演练。[WebDAV 驱动](https://rclone.org/webdav/) |

对私有网关，在 rclone 新建 `webdav` 远端，选择 `other`，URL 指向已部署的 HTTPS WebDAV 根（例如 `https://backup.example.org/dav/`），配置机构服务账号。在文件 `.local/platform/backup-locations.json` 登记已有对应远端的目录。以下名称均为示例。只填写已配置的目标。可用 `NH_BACKUP_LOCATIONS_FILE` 指定配置文件路径。

```json
{
  "icloud": "apple:Ankang/Backups",
  "115": "openlist:115/Ankang/Backups",
  "baidu": "openlist:baidu/Ankang/Backups",
  "offsite": "second-site:Ankang/Backups"
}
```

在总管理员的「备份与恢复」点「连接」。后台会对该目标补传已有的可用本机快照。变更登记的远端路径后须在界面重新连接。用「立即创建快照」和「异地已校验」验收实际账户授权、空间和回读能力。每个机构实例独立设置 `NH_BACKUP_LOCATIONS_FILE`、rclone 配置和业务恢复密钥。

## 原部署不可用时恢复

在另一台主机安装相同版本的应用、SQLCipher 依赖、rclone，重新授权云端目录。取出独立保管的恢复密钥或用 `unwrap-key` 解锁离线恢复材料。以下两条网盘命令可在原工作库丢失时运行。用第一条列出的完整对象名替换示例参数。

```bash
python3 manage_backups.py list-cloud 115
python3 manage_backups.py download 115 '完整对象名.akbak' /private/recovery/received.akbak
python3 manage_storage.py --db /private/recovery/checked.sqlite3 restore /private/recovery/received.akbak --recovery-key-file /private/keys/institution.key
python3 manage_storage.py --db /private/recovery/checked.sqlite3 verify
```

恢复会核对文件认证、加密数据库页面与结构，目标必须是新路径。核验院区、员工账号、老人档案数量及抽样医疗原图后，再把应用指向核验过的工作库。用户需要重新登录。每个机构使用独立恢复密钥；需另外保管业务恢复材料、平台运维凭据和网盘授权。持有密文和有效恢复密钥的授权运维人员能够离线恢复资料。[密钥封装、保管和灾备](storage.md)
