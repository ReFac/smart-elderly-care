# 机构数据加密与恢复

[文档导航](README.md)

## 存储范围

| 数据 | 本机保存位置 | 随机构快照恢复 |
| --- | --- | --- |
| 长辈和员工档案、病历原图、OCR/ASR 归档、照护及经营台账、授权与审计 | 机构 SQLCipher 库 | 是 |
| 同源导览图片、楼层底图、指定导入的历史附件与业务文件包 | 机构 SQLCipher 库 | 是 |
| 外站导览 | 数据库保存已登记的 URL，素材由来源站保管 | 恢复 URL。需把图片导入本机构才能随库恢复文件 |
| DeepSeek 运行凭据、废弃系统的环境文件 | 平台独立运维密库或部署方的凭据管理器 | 由运营方单独保管及恢复 |
| 业务主密钥、平台主密钥及各自的恢复材料 | 独立的宿主机私密文件或 OS 密钥挂载 | 分开保管；快照配送只传机构密文包 |

服务使用 SQLCipher 对 SQLite 数据页和回滚/WAL 日志加密，临时工作表放在内存。操作系统可看到文件路径、大小和修改时间。宿主机服务账号及能读取该进程内存的系统管理员属于受信边界，业务账号通过平台角色和分院范围访问数据。部署方应同时保护系统交换空间、磁盘、故障转储和反向代理日志。[SQLCipher API](https://www.zetetic.net/sqlcipher/sqlcipher-api/)

首次建库时生成 32 字节随机主密钥，默认位于库旁的 `.<库文件名>.storage-key`，Unix 权限为 0600。生产可设置 `NH_STORAGE_KEY_FILE` 指向服务账号独占的普通文件，例如挂载在 `/run/secrets/eldercare-storage-key` 的 32 字节随机二进制密钥。每个客户使用独立密钥。工作目录使用支持 SQLite 文件锁、硬链接以及原子重命名的本机文件系统。启动时验证文件权限以及实际数据库可读性。原数据库丢失密钥时服务拒绝启动。

## 小型服务器与并发

HTTP 服务按可用 CPU 设置有上限的请求线程，并识别 Linux 容器的 CPU 配额。大型上传、原件读取、录音转写和长时间模型请求另有并发上限，达到容量时返回 HTTP 503 和重试间隔。上传在读取文件前检查容量。部署可通过 `NH_HTTP_WORKERS` 和 `NH_HTTP_HEAVY_WORKERS` 调整数值。以 2 vCPU 为例，默认允许 8 个活跃连接，其中最多 2 个执行高开销请求。

## 从旧版本迁移

1. 停止旧服务和其他数据库写入程序，确认数据库所在目录有复制一份整库的空间。安装 `python3 -m pip install -r requirements-storage.txt`。如果旧版本已经备份过明文，先确认这些副本的保管位置。
2. 执行以下命令。迁移将已有提交及 WAL 纳入加密导出，保留当时的修订号及库版本，通过 SQLCipher 页面认证和 SQLite 完整性检查后原子替换旧库。首次启动时再按程序版本升级业务表。

```bash
python3 manage_storage.py --db .local/workspace.sqlite3 migrate
python3 manage_storage.py --db .local/workspace.sqlite3 verify
```

迁移会依据现有账号摘要核对旧版 `.owner-password`，匹配后删除旧凭据文件。未匹配的同目录文件可能属于另一机构，由宿主机管理员核实归属。新版账号库仅保存加盐摘要。已有账号持原密码登录，或按已验证渠道改密。[账号找回与灾备后的绑定](access.md)

3. 按文件逐个导入旧版同源图片和历史附件。命令拒绝符号链接，按 SHA-256 回读复核已提交内容。同名同内容可重试，修改内容使用新编号。以下路径是操作示例。图片需与扩展名匹配，最大 32 MiB。

```bash
python3 manage_storage.py --db .local/workspace.sqlite3 import-tour lobby.jpg /approved/originals/lobby.jpg
python3 manage_storage.py --db .local/workspace.sqlite3 import-file legacy/dev.db /approved/originals/dev.db
```

旧历史库作为逐字节原件归档。平台只处理明确指定的文件。导入成功和重复导入均报告原文件大小及摘要。只有宿主机管理员显式执行 `export-file` 时才会产生明文原件，目标须为新路径。应使用受控加密卷核对源文件与恢复出的文件摘要。确认完整恢复后由管理员清理失去用途的旧原件及历史备份。删除目录条目无法保证物理存储上的历史页或旧快照被擦除。

## 备份、恢复密钥与演练

每个 `.akbak` 是独立的全量时间点。SQLCipher 在线备份先固定开始读取时的 WAL 视图及其已提交业务修订号，期间业务可继续写入。复制全部业务表后立即释放该视图，复核副本修订号、页面认证及数据库结构，再以 AES-256-GCM 封装。每份快照有独立随机盐、派生密钥和随机 nonce。文件头和密文都受认证，SHA-256 可用来核对跨位置复制的字节。中断不会发布部分文件。定时与云端副本状态通过总管理员的备份页面查看，连接方式与异地核验见[备份调度和云端副本](backups.md)。服务处于关机期间无法生成当天时点，重新启动后按调度状态补建最新的可恢复点。

```bash
python3 manage_storage.py --db .local/workspace.sqlite3 snapshot /secured-points/office.akbak
python3 manage_storage.py --db .local/workspace.sqlite3 wrap-key /offline-recovery/office.akkey
```

`wrap-key` 在本机终端两次提示输入恢复口令，参数和标准输出不含口令。使用独立保管的高熵口令，程序最低接受 14 个字符。恢复材料以 scrypt（N=131072、r=8、p=1，约 128 MiB 内存）生成包裹密钥，再用 AES-256-GCM 封装主密钥。把恢复材料和口令分开保管，并与机构快照分处不同安全位置。两者均丢失且原主密钥不可用时，无法恢复资料。

在独立恢复主机或独立目录中执行演练；目标使用新文件名。命令会在新库对应位置安装恢复出的密钥，已配置的 `NH_STORAGE_KEY_FILE` 则必须指向同一密钥。旧会话在恢复库中失效，需要重新登录。原机的本地快照索引、未完成的传输、核验记录和网盘启用状态一并重置，原有业务审计仍可查询。新库启动后重新创建本机时间点，由总管理员重新连接目标网盘。原服务和原文件可继续运行。

```bash
python3 manage_storage.py --db /recovery/workspace.sqlite3 unwrap-key /offline-recovery/office.akkey --key-out /recovery/office.key
python3 manage_storage.py --db /recovery/workspace.sqlite3 restore /secured-points/office.akbak --recovery-key-file /recovery/office.key
python3 manage_storage.py --db /recovery/workspace.sqlite3 verify
python3 manage_storage.py --db /recovery/workspace.sqlite3 export-file legacy/dev.db /private-verification/dev.db
```

核对恢复输出的修订号，登录并抽查员工、长辈、原图、导览授权及归档摘要。恢复到历史时点也会恢复当时的人员权限以及转介授权。将恢复库重新开放给员工和外部收件人前，核实并重放时点之后的撤权、离职、转院与撤回同意记录。启用新的生产库前停止旧服务并确认数据与密钥配对。

## 平台运维凭据

服务先使用平台注入的 `DEEPSEEK_API_KEY` 或明确指定的 0600 `NH_DEEPSEEK_KEY_FILE`。本地部署可改用默认的独立运维密库 `.local/platform/secrets.sqlite3`，其中的凭据仅在后端调用时读入内存。使用 `NH_PLATFORM_VAULT` 可指定另一个路径。`NH_PLATFORM_KEY_FILE` 可指向独立的 32 字节 OS 私密挂载；默认使用库旁的 `.<库文件名>.platform-key`。该密钥与机构业务主密钥分别生成，运维密库由平台运营方管理。

```bash
python3 manage_secrets.py import-file deepseek .local/platform/deepseek.key --remove-source
python3 manage_secrets.py verify deepseek
python3 manage_secrets.py wrap-key /offline-operator/operational.akkey
```

迁移命令先重新打开运维密库，比对实际内容及源文件身份，再移除指定旧文件。完成后取消原先指向这个旧文件的部署变量。新装和轮换可用 `python3 manage_secrets.py set-deepseek`，在本机终端遮罩输入凭据。历史 `.env` 等可用 `--vault /offline-operator/retired.sqlite3` 和单独的档案编号导入另一离线库。由运营方单独保管停机状态下的运维库密文副本及其恢复材料。业务备份任务不会遍历或上传运维目录。需要重建时，先还原该库密文，用 `manage_secrets.py --vault <运维库> unwrap-key <恢复材料> --key-out <新的运维密钥路径>` 解封，指定 `NH_PLATFORM_KEY_FILE` 后执行 `verify deepseek`。

## 业务文件

民政报表和院外转介下载为 `.akdoc`。生成内容使用独立的 AES-256-GCM 子密钥封装一份，并在业务库登记密文及摘要。报告送出后按送出时保存的固定版本导出。草稿导出保留当时的内容。转介包限定本人同意的资料范围，撤回授权会使已有包在当前工作库中即时失效。

收件人须登录发件机构的工作台，使用「民政报送」或「院外衔接」中的「打开加密文件」。服务器每次检查登录、报送或临床权限，以及转介对象的分院和当前授权序号。每次导出、查阅均留审计。对接程序可通过受授权的报送版本 API 获取固定数据集，接收方负责自己的系统与落盘保护。
