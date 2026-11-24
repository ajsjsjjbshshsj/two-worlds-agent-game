# T17.2.3 · 封闭 Playtest 部署

适用于本机演练或后续经批准的隔离主机。试玩工程、容器验收、云端验收和真人授权分别签核。本文的域名、地址和测试包均为示例，素材引用不构成版权授权。

~~~mermaid
flowchart LR
    P["已获准的设备 · 每设备独立 VPN IPv4"] -->|"HTTPS / WSS · TCP 443"| G["Nginx · 直连 IP 白名单"]
    G -->|"内部 app 网络"| F["Vue 静态前端 · 8080"]
    G -->|"同源 API / 媒体 / Upgrade · app"| B["FastAPI · twoworlds.playtest · 8000"]
    B -->|"内部 data 网络 · SCRAM-SHA-256"| M["单节点认证 MongoDB · 27017"]
    M --> V["项目独立数据卷"]
    B --> C["外部发布包与签核清单 · 只读"]
    O["组织者 · 本地 Docker 操作权限"] -->|"一次性 CLI 容器"| B
~~~

## 主机与配置

使用独立 Linux 主机、Docker Engine 与 Compose v2.33.1 或更新版本。选择独立 Docker project、专用数据卷和受限的 VPN 接口。防火墙只允许经审批的 VPN 入口访问 TCP 443。禁止非受控主机访问 Docker socket、管理端口和内部网桥。生产数据库、容器网络、自动备份、存储卷、域名 Cookie 和密钥与 Playtest 分开。MongoDB 在本项目的内部 `data` 网络通信，单主机内的 Mongo 流量由网桥与宿主机策略保护。

将下列**非秘密配置**保存为仓库外的专用 env 文件。按本地实际绝对路径替换示例值。

~~~dotenv
TWOWORLDS_PLAYTEST_HOST=playtest.example.invalid
TWOWORLDS_PLAYTEST_BIND_IP=127.0.0.1
TWOWORLDS_PLAYTEST_ALLOWLIST=192.0.2.7,192.0.2.8
TWOWORLDS_PLAYTEST_MONGO_DATABASE=twoworlds_playtest_closed
TWOWORLDS_PLAYTEST_TLS_DIR=/srv/tw-playtest/tls
TWOWORLDS_PLAYTEST_SECRET_DIR=/srv/tw-playtest/secrets
TWOWORLDS_PLAYTEST_PUBLICATION_ROOT=/srv/tw-playtest/releases
TWOWORLDS_PLAYTEST_APPROVAL_FILE=/srv/tw-playtest/content-approval.json
TWOWORLDS_PLAYTEST_CONTENT_PURPOSE=participant
~~~

白名单只接受逗号分隔的单个 IPv4 地址，当前不接受网段、通配符或 IPv6。使用每设备分配独立源 IP 的 VPN。以 Nginx 实际看到的 TCP 源地址验收；若经 NAT、HTTP 代理或共享出口导致地址合并，先修正网络，禁止将共享出口或容器桥接网关放入白名单。应用只信任 Compose 固定的 Nginx app 网桥地址用于客户端 IP/限流。入口 ACL 仍只使用直连地址，忽略客户端传入的转发头。非回环绑定须指向经批准的 IPv4 接口。只有 `gateway` 发布端口，且没有 HTTP 监听或重定向入口。内部 app 子网与现有网络冲突时用 `TWOWORLDS_PLAYTEST_APP_SUBNET`、`TWOWORLDS_PLAYTEST_APP_RANGE`、`TWOWORLDS_PLAYTEST_GATEWAY_IP` 一并重设并复验。

持久化卷仅由 Playtest MongoDB 使用。官方 MongoDB 入口第一次通过容器回环初始化，最终监听使用 `--auth`。初始化创建 `playtest_admin`（维护使用）和 `playtest_app`（只有目标库 `readWrite`）。后端只挂载应用密码和校验密钥文件，固定连接 `playtest-mongo`，复用 Playtest 的身份、同一进程匿名访问和单节点检查。管理员密码只挂载到数据库容器。修改已有卷的密码文件不会轮换数据库账号，须先在隔离窗口执行数据库改密并同步更新挂载。首次初始化中断时停止开测并核对数据卷，按[运维说明](t17-2-3-operations.md)处理。

在仓库外用秘密管理工具生成三个独立的 32 字节随机十六进制值。使用主机 root 管理目录，以下示例使用 Linux 默认未重映射的容器 UID/GID。启用 rootless Docker 或 UID 映射时，改用所对应的宿主机身份并复核实际读取权限。

~~~bash
sudo install -d -m 0700 /srv/tw-playtest/secrets
sudo sh -eu -c '
  umask 077
  set -C
  for name in mongo-admin-password mongo-app-password verification-secret; do
    openssl rand -hex 32 > "/srv/tw-playtest/secrets/$name"
  done
'
sudo chgrp 999 /srv/tw-playtest/secrets/mongo-admin-password
sudo chgrp 10001 /srv/tw-playtest/secrets/{mongo-app-password,verification-secret}
sudo chmod 0640 /srv/tw-playtest/secrets/{mongo-admin-password,mongo-app-password,verification-secret}
~~~

证书与私钥由平台运维负责人管理更新。实际试玩使用参与设备信任的证书链及正确 SAN。将实体文件 `fullchain.pem` 与 `privkey.pem` 安装到外部 TLS 目录，授予网关组（容器 GID 101）读取权限。目录建议 `0750`，私钥 `0640`。避免指向外部证书存储的软链接。每次签发或续期先核对域名、有效期、证书链和私钥匹配，再替换文件并执行 `dc up -d --force-recreate --wait gateway`，从允许设备检查 TLS 与 WSS。缺失、不可读或格式/密钥匹配错误会阻止网关启动。浏览器继续验证名称、信任链和有效期。CI 的自签证书仅用于临时容器验收。

## 发布目录与开测条件

将内容负责人签核的封存包放入独立发布目录，后台只读挂载它。内容负责人逐项检查授权证据和公开信息，记录批准的版本与对应 `release.json` 的 SHA-256。清单可用 `sha256sum <发布目录>/<剧本>/<版本>/release.json` 核对，格式如下，示例哈希必须替换。

~~~json
{
  "purpose": "participant",
  "releases": {
    "lighthouse/1.0.0": "<该封存 release.json 的 SHA-256>"
  }
}
~~~

应用启动先验证发布包既有完整性，再核对清单用途、完整版本集合及每份封存记录的摘要。缺少清单、空目录、漏签或多带版本、摘要不符都会在连接数据库前失败。签核清单由有权限的内容负责人保管，它是本地摘要核准记录，素材来源和法律授权仍需人工验证。常规参与者启动拒绝项目 CI 的 test-only 标记。内部容器演练显式使用 `internal-drill` 清单和回环端口，只加载合成测试包。正式环境包和开发草稿均保留在各自路径，Playtest 没有回退逻辑。两篇剧本的正式素材均保留待审核状态。

## 启动与核对

在仓库根目录从选定的 Playtest 项目执行。避免同一 Docker 主机上的活跃项目复用外部目录、静态子网或绑定地址。

~~~bash
export PLAYTEST_ENV=/srv/tw-playtest/playtest.env
export PLAYTEST_PROJECT=twoworlds-playtest-closed

dc() {
  docker compose --env-file "$PLAYTEST_ENV" -p "$PLAYTEST_PROJECT" -f compose.playtest.yml "$@"
}

dc config --quiet
dc build
dc up -d --wait
dc ps
~~~

这里只提供部署命令。本轮实际演练使用随机项目、合成数据和自签 TLS。清理命令及实际开测的前置核对见 [Playtest 运维说明](t17-2-3-operations.md)。

## 安全验收清单

| 检查 | 本机/CI 验收 | 获批云环境复验 |
| --- | --- | --- |
| 入口 | 白名单内 HTTPS 200，白名单外 UI、API、媒体和 WSS 403；伪造转发头无效 | 复验 VPN 地址保存、独立设备、宿主机/云防火墙及仅 443 可达 |
| 传输与会话 | TLS 1.2/1.3、HTTP 无入口、Secure/HttpOnly Cookie、精确 Origin、真实 WSS 快照 | 复验证书链、域名、续期、真实设备和 VPN 切换 |
| MongoDB | 容器真实认证、无凭据拒绝、角色受限及独立卷 | 复验宿主机网络、凭据权限、卷与备份保留状态 |
| 账号与媒体 | 预创建 CLI、关闭公开建号和找回、本人媒体权限、匿名和搭档权限 | 经授权后核对预发别名、独立交付和受限实际发布包 |
| 内容 | 损坏、空库、清单不符及 test-only 路径、只读发布 | 由内容负责人签核使用范围、素材授权和参与者版本 |
| 撤场 | 停入口、撤销会话、拒绝未确认删库、相邻测试库保持完整、单独删除卷 | 分别记录关闭入口、删除/保留各项数据及证据，验收远程快照和日志 |

## 待决事项

| 事项 | 等待决定或提供 |
| --- | --- |
| 内容 | 采用获准的合成占位素材，或等待正式素材及授权 |
| 云厂商 | 阿里云或 AWS |
| 地域 | 实际服务器区域和数据存放地域 |
| TLS | 实际域名、证书、签发与续期负责人 |
| 访问范围 | VPN 方案及允许设备的独立地址 |
| 成本 | 服务器预算、账户、付款授权 |
| 真机范围 | 首轮是否同时支持 iPhone 和 Android |

在明确批准前，维持本机演练范围，真人开测、云资源购买和域名配置均待授权。
