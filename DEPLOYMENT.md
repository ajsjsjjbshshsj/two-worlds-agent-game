# TwoWorlds 生产架构与上线验收

按 [RUNBOOK](RUNBOOK.md) 操作。默认 Compose 提供正式应用拓扑，公开服务前需要完成本页的 MongoDB 访问控制和真实外部系统验收。

封闭试玩使用独立 Compose、身份认证 MongoDB 和设备白名单。配置及退场验收见 [Playtest 部署说明](docs/playtest/t17-2-3-deployment.md)与[运维说明](docs/playtest/t17-2-3-operations.md)。

## 服务与数据

- Nginx 网关承接浏览器 HTTPS 和 WSS，明文入口重定向至配置的 HTTPS 域名。静态请求交给 Vue 构建产物，`/api` 和 WSS Upgrade 都由 FastAPI 处理。
- FastAPI、Vue 容器和 MongoDB 均没有宿主机端口映射。MongoDB 位于单独的内部数据网，FastAPI 同时接入网关网和数据网。网关覆盖转发头，FastAPI 只信任固定网关地址。
- 会话使用 Secure/HttpOnly/SameSite=Lax Cookie，HTTP 写请求和 WebSocket 使用精确 HTTPS Origin。生产强制 SMTP，AI 默认 Demo。私钥通过只读目录挂载，SMTP、Mongo 和 AI 凭据由部署端注入后端运行环境。正式前端构建同源 API 地址。
- 持久化卷为 `mongo_data`。库内保存账号、会话、验证码记录、双人关系、存档、命令回执、限频与 AI 计量。剧本版本及素材随已批准的发布版本保存，备份业务库时一并登记镜像和剧本版本。凭据、验证密钥与证书走独立保管流程。
- `compose.demo.yml` 使用 SQLite 和自己的 `sqlite_data`，默认 Console 邮件与 Demo AI。使用独立项目名及端口运行 Demo。项目读取正式模板时，给 Demo 明确设定 `TWOWORLDS_EMAIL_MODE=console`。

## MongoDB 访问控制改造

现有 `compose.yml` 启动 MongoDB 7.0.48 standalone，网络隔离和命名卷已具备，默认未启用数据库认证。接入内部数据网的进程、同主机 Docker 操作者或被攻陷的 backend 可以直接访问数据库。**已验证的 HTTPS/WSS 和内部网络不能替代数据库身份认证。**

优先使用已启用访问控制的 MongoDB，并把应用的 `MONGO_URI` 指向该服务。继续使用现有 Mongo 容器时，可在同一维护窗口采取以下最小改造，保留卷和业务模型。

1. 停止网关、backend 和其他业务写入，确认可用备份和回退方案。对现有卷使用 `docker compose exec mongo mongosh` 从容器内建立管理员和权限分离账号。通过 `passwordPrompt()` 输入来自密钥存储的密码。
2. 在 `admin` 建立运维管理员。在业务库建立应用账号 `readWrite` 和独立备份账号 `read`。在指定的新目标库单独建立恢复账号 `readWrite`。账号仅用于各自工作，应用不使用管理员账号。
3. 以受控本地 Compose 覆盖文件启用 `mongod --auth`，将应用 URI 切换为该库认证账号，密码中的保留字符按 URI 规则编码。已有卷的账号在 Mongo 内创建，初始化环境变量只应用于首次初始化空卷。

以下是在访问控制改造窗口内、从容器内启动的 `mongosh` 示例。将 `twoworlds` 替换为实际业务库。恢复账号在恢复实例另行创建。

```javascript
db.getSiblingDB("admin").createUser({
  user: "tw-ops",
  pwd: passwordPrompt(),
  roles: ["userAdminAnyDatabase"]
})
db.getSiblingDB("twoworlds").createUser({
  user: "tw-app",
  pwd: passwordPrompt(),
  roles: ["readWrite"]
})
db.getSiblingDB("twoworlds").createUser({
  user: "tw-backup",
  pwd: passwordPrompt(),
  roles: ["read"]
})
```

`--auth` 的覆盖文件内容如下。使用该文件时，每条正式 Compose 命令都带上两个 `-f` 参数。

```yaml
services:
  mongo:
    command: ["mongod", "--auth"]
```

重建容器后检查匿名读取被拒绝、受限账号可工作、应用 readiness 和备份恢复均通过。上例为待部署主机验证的迁移方案，仓库默认 Compose 保留现有兼容性。临时环境已使用认证验证上述三种业务库角色。更严格的角色拆分、Mongo TLS、replica set 和高可用落为后续主机运维工作。

## 升级、备份和恢复

发布使用审查通过的提交及对应镜像，先在隔离环境演练升级与回滚。备份 standalone 前停写，完整归档应用库并验证 SHA-256，通过 age 或获批存储保护备份静态数据。保留至少一个通过恢复验证的独立副本，备份目录与 MongoDB 卷分开保管。保留期限和异地副本频率由实际 RPO 决定。按备份大小、恢复耗时和应用验收计算 RTO，演练结果对本机合成样本有效。

恢复首选独立 MongoDB 实例的空库。先使用原应用提交和对应剧本验证兼容性。脚本只允许显式新目标，已存在的集合会阻止恢复。正式应用切换前保留原库，人工审批流量切换和事故期间的会话处理。备份后的写入不会自动合并，升级或恢复窗口内应维持停写直至明确切换。

## 正式上线验收

- [ ] 真实主机资源、权限、防火墙、DNS 和 80/443 的对外入口核对完成。
- [ ] 证书链、域名、续期重载和 HTTPS/WSS 在正式入口实测。
- [ ] Mongo 认证启用，匿名访问拒绝，应用、备份和恢复角色分离，数据端口未公开。
- [ ] SMTP 在获准环境验收，日志无凭据、验证码、邀请与私聊。Provider 若启用，已有独立授权、预算和限额。
- [ ] Probe 核对正常和数据库故障，正式用户会话和 A/B 隐私核对通过。
- [ ] 加密异地备份、密钥保管、保留期、RPO/RTO、定期恢复和回退责任人已确认。
- [ ] 恢复副本在同版本启动，账号、关系、存档和操作回执可查，审批后才切换流量。

本轮本地与 CI 结果见 [T15.3 报告](docs/reports/t15-3-production-runbook-backup-restore.md)。这些检查点按正式环境的实际结果逐项确认。
