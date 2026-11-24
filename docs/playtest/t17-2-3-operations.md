# T17.2.3 · 组织者运维与撤场

本手册沿用 [Playtest 部署说明](t17-2-3-deployment.md#启动与核对) 中从仓库根目录定义的 `dc`、`PLAYTEST_ENV` 和 `PLAYTEST_PROJECT`。操作人员先通过 `dc ps` 核对项目和服务，通过 `dc config --quiet` 核对配置。普通运维避免输出秘密文件、URI、会话 Cookie 和玩家凭据。

## 建号与交付

遵循 [组织者建号手册](t17-2-2-2-account-provisioning.md)。组织者在仓库外建立专用交付目录，保存已核准的 JSON 别名，别名不用真实姓名、邮箱或手机号。命令使用一次性容器和既有 CLI。仅在实际开测获准后建真人试玩账号。

Linux 主机准备 `0700` 交付目录及 `0600` 的别名输入文件，归属与容器 UID/GID 10001 对应的专用身份。组织者通过同一受控身份读取文件。不要给其他用户赋权或将目录放入同步盘。

~~~bash
export PLAYTEST_HANDOFF=/srv/tw-playtest/handoff
dc up -d --wait playtest-mongo
dc run --rm --no-deps -T   --volume "$PLAYTEST_HANDOFF:/handoff" backend   python -m twoworlds.provision_playtest_accounts   /handoff/approved-aliases.json /handoff/batch-01.jsonl
~~~

核对批次结果，只通过独立安全渠道发放确认创建的单人凭据。玩家通过获准 VPN 设备在 HTTPS 页面使用别名和初始密码登录，取得新会话。建号不会发邮件或初始化 Session。保留不含凭据的审计记录，确认分发后单独移除凭据文件，按试玩同意约定管理保留期限。

## 关闭、撤销、核对

1. 在需要撤场时先撤销 VPN 入口许可或阻断该主机的试玩 443，确认独立设备已经无法请求，然后 `dc stop gateway` 断开已有 HTTP/WSS 入口。
2. `dc stop frontend backend` 停止后端写入，只留专用 MongoDB。先核对 `dc ps -a`，确保无其他 Playtest 写入者、临时建号容器、备份任务或正式数据库连接。
3. 运行以下默认 dry-run。在组织者的安全终端核对数据库名、别名、账号数量和会话计数。若出现意外账号或来源，保留证据并停止删除。脚本固定连接 MongoDB 容器的回环端口、拒绝非 Playtest 库名和不符合别名格式的账号，退出状态非零表示拒绝或失败。

~~~bash
dc exec -T -e PLAYTEST_CONFIRM= playtest-mongo \
  mongosh --quiet --nodb --file /opt/playtest/maintenance.js
~~~

4. 明确批准后，手工把上一步核准的实际库名填入 `REVOKE:`。重新 dry-run 验证会话为零，保持入口关闭。撤销仅使旧 Cookie 无效；保留账号时，初始密码仍具备登录能力。

~~~bash
dc exec -T -e PLAYTEST_CONFIRM=REVOKE:twoworlds_playtest_closed playtest-mongo \
  mongosh --quiet --nodb --file /opt/playtest/maintenance.js
~~~

5. 若已有人员批准清除玩家数据，先确认保留协议、备份处置和批准库名，再手工填入精确 `DROP:` 确认。命令要求先撤销会话，并从同一 Mongo 容器读取维护专用凭据。执行后检查脚本回显 `dropped`，再次 dry-run 显示空列表。清除数据库集合涉及全部该库账号、配对和存档，只能用于获准的专用库。

~~~bash
dc exec -T -e PLAYTEST_CONFIRM=DROP:twoworlds_playtest_closed playtest-mongo \
  mongosh --quiet --nodb --file /opt/playtest/maintenance.js
~~~

## 分开清理各类资源

| 操作 | 命令或验收 |
| --- | --- |
| 仅停止容器 | `dc stop`。保留容器、账号和持久卷 |
| 删除容器与网络 | `dc down`。普通命令保留命名卷，删除容器后复核本机容器日志状态 |
| 删除玩家数据 | 使用上面的显式 `DROP:<库名>`；销毁前单独确认授权 |
| 销毁数据库卷 | `docker volume inspect "${PLAYTEST_PROJECT}_mongo_data"`。核对 Compose project 标签、挂载者、快照与保留期。审批后再执行 `docker volume rm "${PLAYTEST_PROJECT}_mongo_data"`，并确认 `inspect` 找不到该卷 |
| 删除备份与快照 | 单列每份 Playtest 归档、云快照和副本的路径或 ID、存储位置及保留期限，逐项审批并复核。清库或删卷不会移除独立备份 |
| 临时发布、证书和凭据文件 | 列出仓库外测试资产与交付清单，核对仅含该项目测试数据，经审批后逐个移除。保留获准的原始素材及授权记录，撤销或轮换专用密钥 |
| 日志及终端文件 | 按保留期处理主机日志、归档、手工导出及临时文件。组织者清理客户端站点数据和离线缓存，并核对浏览器没有残余私密内容 |
| 最终隔离核验 | 检查 `dc ps -a`、该项目卷、Docker 网络及主机监听；核对部署记录中的 Mongo 地址固定为 Playtest 服务，没有独立或正式库的连接凭据；保留去标识的验收结论 |

普通启动和停止均保留数据库，删除卷与删除备份各需单独确认。首次 Mongo 初始化失败且已创建数据卷时，先保护并核对卷内容。若是经核实的空白演练卷，按本表批准删除并重新初始化。

## 本机演练入口

在 `backend/` 运行以下命令。测试为临时随机项目生成测试证书、签核清单和合成数据，启动实际 MongoDB 和 Nginx，并用不同来源的 TCP 客户端验证。测试清除自己创建的临时卷、容器、合成凭据和发布包。已有站点无需停机。

~~~bash
uv run --locked python -m tests.playtest_deployment
~~~

也可运行 `uv run --locked pytest tests/api/test_playtest.py tests/api/test_provision_playtest_accounts.py` 查看独立运行时和账号工具的真实 MongoDB 测试。普通全量 pytest 同时使用 SQLite 默认仓储及显式 MongoDB 用例，需配置一次性回归 MongoDB。云防火墙、真实 VPN 地址、实际 CA、真实移动设备、素材授权及真人授权另行验收。
