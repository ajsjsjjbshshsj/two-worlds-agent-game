# TwoWorlds 生产运维手册

先确认发布版本已获审查。所有示例在该版本的仓库根目录运行。以下步骤以 Linux 上的 Docker Compose v2 为准。调整公网入口、修改数据库访问控制、切换数据库或恢复服务，都应在确认维护窗口后进行。

## 1. 准备主机和入口

- 主机需要 Docker Engine、Compose v2、Bash、GNU coreutils、util-linux（`flock`）以及 curl。使用加密备份时安装 age 和 age-keygen。预留构建镜像、Mongo 工作集、持久卷和至少两份备份的空间。
- 按 [Docker 官方安装说明](https://docs.docker.com/engine/install/) 安装对应发行版的软件包。从受控运维账号确认 Docker daemon 正在运行，验证 Docker 和 Compose 版本。
- 为获批的正式主机配置 DNS A 记录，并仅在入口有 IPv6 路由时配置 AAAA。等待解析生效，核对目标地址及防火墙。对外只开放网关需要的 TCP 80、443，管理入口按主机策略限制。
- 通过已有证书管理流程为该 DNS 名准备合法证书链和私钥，分别命名为 `fullchain.pem`、`privkey.pem`。存放于宿主机受保护目录。网关以只读方式挂载整目录，文件与符号链接目标都要在容器内可读。核对到期日和域名后再开放流量。

```bash
docker version
docker compose version
command -v flock sha256sum curl
openssl x509 -in "$tls_directory/fullchain.pem" -noout -dates -ext subjectAltName
```

`tls_directory` 为部署人员设置的宿主机证书目录。证书续期后替换该目录内文件，按下文检查并重载网关。

## 2. 配置运行环境

用 `umask 077` 创建本机 `.env`，按 [.env.example](.env.example) 配置或从受控部署密钥存储注入。通过 `docker compose config --quiet` 检查语法。运维工单只记录配置项名称和验证结果。

| 项目 | 正式配置 |
| --- | --- |
| HTTPS | `TWOWORLDS_PUBLIC_HOST` 填小写 DNS 名，`TWOWORLDS_BIND_IP` 设为获批监听地址，`TWOWORLDS_TLS_DIR` 指向上节证书目录 |
| Origin 与 Cookie | Compose 由 DNS 名派生唯一 HTTPS Origin，自动启用 Secure Cookie，并将网关 IP 设为唯一可信代理 |
| MongoDB | `MONGO_DATABASE` 为应用库，`MONGO_URI` 使用已启用访问控制的数据库和该库专用应用账号。MongoDB 安全基线见 [部署说明](DEPLOYMENT.md) |
| 会话与验证码 | `TWOWORLDS_VERIFICATION_SECRET` 使用独立的随机值，由密钥存储保管。生成时可用 `openssl rand -hex 32` |
| SMTP | `TWOWORLDS_EMAIL_MODE=smtp`，填写 `SMTP_HOST`、`SMTP_FROM` 和合法的 `SMTP_PORT`。配置 `SMTP_USERNAME` 时同时注入 `SMTP_PASSWORD`。465 使用 TLS，其他端口使用 STARTTLS |
| AI | 默认 `TWOWORLDS_AI_MODE=demo`。经授权启用 provider 时，按模板完整配置 HTTPS 地址、模型、输入输出限额、超时、价格和 UTC 日预算。仅向后端运行环境注入 `TWOWORLDS_AI_API_KEY` |

**公网启用前先处理 MongoDB 访问控制。** 基线 Compose 内置 MongoDB 使用 standalone 和内部网络，默认没有数据库认证。使用已有认证的专用 MongoDB，或采用 [最小兼容改造](DEPLOYMENT.md#mongodb-访问控制改造)。应用运行账号只需业务库的 `readWrite`。备份和恢复使用各自的运维账号。

## 3. 启动及验收

```bash
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
docker compose exec -T gateway nginx -t
```

在宿主机内部检查探针。公网入口上的 `/health/` 返回 404。

```bash
docker compose exec -T backend python - <<'PY'
from urllib.request import ProxyHandler, build_opener

opener = build_opener(ProxyHandler({}))
for route in ("live", "ready"):
    with opener.open("http://127.0.0.1:8000/health/" + route, timeout=4) as response:
        print(route, response.status, response.read().decode())
PY
```

配置并确认正式 DNS 后，从批准的测试端检查外部入口。`public_host` 取 `TWOWORLDS_PUBLIC_HOST`。`curl` 保持默认证书验证。

```bash
curl --fail --silent --show-error --head "http://$public_host/"
curl --fail --silent --show-error "https://$public_host/api/scripts"
```

核对 HTTP 308、HTTPS 证书链、Secure/HttpOnly/SameSite=Lax Cookie、同域 WSS 握手及 A/B 角色视角。TLS 与 WSS 的临时本地复验入口见 [T15.2 报告](docs/reports/t15-2-secure-deployment.md)。上线验收使用获批测试账号，并按 [验收清单](DEPLOYMENT.md#正式上线验收) 记录证据。

## 4. 日志、维护和回滚

```bash
docker compose logs --tail=50 gateway backend frontend mongo
docker compose exec -T gateway nginx -t
docker compose exec -T gateway nginx -s reload
docker compose restart backend
docker compose ps
```

| 现象 | 先核对 |
| --- | --- |
| HTTPS 失败或网关未启动 | DNS、80/443 监听地址、证书域名和挂载、`nginx -t` |
| API 502 / 504 | backend 状态、内部 readiness、网关与 backend 的私网连接 |
| ready 503，live 200 | MongoDB 状态、连接配置、认证与角色、磁盘空间。进程可能恢复，先确认依赖 |
| 生产启动提示配置错误 | SMTP 主机、端口和发件地址，Mongo URI，HTTPS Origin 与安全 Cookie。对照错误中的变量名称 |
| WSS 403 | 访问域名、单一精确 Origin、会话 Cookie 与失效时间。保持现有校验 |
| 前端更新不一致 | 版本对应的静态镜像、Service Worker 更新与同源 API 可达性 |

升级前记录上一个已审查 Git 提交及镜像标识、备份和剧本发布版本。按下节暂停写入并保存备份，获准后部署下一个已审查版本。确认 ready、登录、API 和 WSS 后再开放流量。直接回滚应用前检查数据兼容性，使用已验证的旧提交或镜像重建并保留 `mongo_data`。如果数据也要回退，恢复到新库再人工批准切换。回滚前后发生的写入需要独立对账。

在独立部署检出中，升级和应用回滚可执行同一命令。将 `selected_release` 设为已批准的目标提交，保持原 Compose 项目名和配置。

```bash
git switch --detach "$selected_release"
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
```

## 5. 备份完整业务库

内置 MongoDB 为 standalone。安排维护窗口，停止业务写入并确认没有后台任务或其他客户端持续写库。`mongodump` 在这个拓扑下提供停写时的逻辑备份。数据库账号和角色需另外由运维配置，发布内容、镜像和密钥在各自的受控位置保留。

操作前设置 `MONGO_DATABASE`、绝对目录 `MONGO_BACKUP_DIR`、age 公钥 `MONGO_BACKUP_RECIPIENT`。`MONGO_BACKUP_RETENTION_DAYS` 默认 30，设为 0 关闭自动清理。使用有源库 `read` 权限的独立账号。传给工具的连接文件为只含 `uri` 的 JSON，URI 可包含编码后的凭据，文件由密钥存储下发，权限为 0600。设置 `MONGO_TOOLS_CONFIG` 为容器内绝对路径。连接值留在文件中。

如需在同一 Docker 私网使用独立工具容器，先设定 `tools_container`、`data_network` 和宿主机上的 `tools_config_file`。`data_network` 为当前 Compose 项目的数据网，可通过 `docker network ls` 和 `docker network inspect` 核对。工具容器使用已验证的 Mongo 7.0.48 镜像。

```bash
docker run -d --name "$tools_container" --network "$data_network" \
  --mount "type=bind,source=$tools_config_file,target=/run/connection.json,readonly" \
  --entrypoint sleep mongo:7.0.48 infinity
docker exec "$tools_container" mongodump --version
export MONGO_CONTAINER="$tools_container"
export MONGO_TOOLS_CONFIG=/run/connection.json
```

当前生产服务正常运行且已批准停写时，可将以下块用于人工备份或受控调度任务。操作员负责配置调度时段、专用账户与失败告警。调度器处理命令退出码并记录生成的目录。不要在不同主机上同时运行同一路径的维护流程。

```bash
(
  set -e
  trap 'docker compose start backend gateway' EXIT
  docker compose stop gateway backend
  MONGO_BACKUP_QUIESCED=1 scripts/mongodb-backup.sh
)
```

成功后打印带 UTC 时间的目录，内含压缩归档、源库名和 SHA-256 文件。备份目录归运行账号所有，权限为 0700。age 公钥在备份端，身份私钥在独立恢复密钥库。具备同等静态加密和访问控制的存储可接收工具的未加密压缩归档。将验证后的整个目录复制到获批的独立加密存储，定期试恢复。备份校验失败时保留旧副本，检查退出原因。

## 6. 恢复、验证及人工切换

1. 在独立的、启用认证的目标 MongoDB 上准备专用恢复账号，其 `readWrite` 限定在一个新命名的空库。将目标工具容器和连接文件显式设为 `MONGO_CONTAINER`、`MONGO_TOOLS_CONFIG`。将 `backup_bundle` 设为需恢复的完整目录。
2. 显式设置 `MONGO_RESTORE_DATABASE` 为新的 `twoworlds_restore_…` 名称。加密备份通过 `MONGO_RESTORE_IDENTITY_FILE` 指向宿主机受保护的 age 身份。目标服务器与目标库确认无其他客户端写入。
3. 执行恢复。脚本校验 SHA-256、解密并验证压缩内容，再执行官方 dry-run。已存在集合的目标会被拒绝，恢复过程不删除数据库或集合。

```bash
scripts/mongodb-restore.sh "$backup_bundle"
```

4. 在与备份相同的应用版本、Mongo 主版本和剧本发布版本上挂接恢复后的新库，给应用账号配置该库的 `readWrite`。启动隔离应用，核验 live/ready、账号登录、配对、存档版本、操作回执和双方私密投影。失败后保持目标隔离，排查后选择另一个空库重试。
5. 切换正式流量是单独操作。经人工确认目标数据、发布版本和维护窗口后，关闭网关入口，变更应用的 `MONGO_DATABASE` 与 `MONGO_URI`，用 `docker compose up -d --no-deps --force-recreate --wait backend` 重建应用。先核对内部探针与目标库，再用 `docker compose start gateway` 恢复入口。原库保留用于对账和回滚。是否保留恢复出的会话由事故处置策略决定。
6. 拆除本次专用工具容器并撤销临时凭据。`docker rm -f "$tools_container"` 只用于上文独立创建的工具容器。

隔离验收命令和实际数据结果见 [T15.3 报告](docs/reports/t15-3-production-runbook-backup-restore.md)。
