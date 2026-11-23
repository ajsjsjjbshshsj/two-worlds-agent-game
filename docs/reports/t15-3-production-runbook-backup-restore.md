# T15.3 · 生产运维与 MongoDB 灾难恢复

已核实 PR #51 合并到 `codex/bootstrap@28f75d51c736f722271860b34dccac271dee67c1`。任务分支为 `codex/t15-3-production-runbook-backup-restore`。

## 交付与运行边界

- [RUNBOOK](../../RUNBOOK.md) 覆盖主机、Docker、DNS、证书、SMTP、AI、启动、探针、日志、升级、回滚、备份及恢复。[DEPLOYMENT](../../DEPLOYMENT.md) 记录生产拓扑、密钥、持久化数据、恢复版本兼容性和正式上线清单。
- [备份脚本](../../scripts/mongodb-backup.sh) 使用 MongoDB 官方 `mongodump --archive --gzip` 归档整套业务命名空间。生成 UTC 目录，校验压缩流和 SHA-256，刷盘后原子发布。目录权限定为 0700，文件由 `umask 077` 保护。只有新归档发布后才扫描过期、格式正确且 SHA-256 完整的旧归档。失败保留旧副本。
- 可选 age 加密采用官方工具。备份端仅用公钥，归档在管道中校验并加密。恢复端先校验 SHA-256，再完整解密并校验 gzip，随后由 `mongorestore --dryRun` 验证归档。
- [恢复脚本](../../scripts/mongodb-restore.sh) 需要显式指定独立的 `twoworlds_restore_*` 空库，拒绝有集合的目标以及配置中的应用库。脚本没有覆盖或删除目标的开关。恢复失败时保持目标隔离，人工核验后另择空库重试。正式切换需人工审批。
- 应用 Compose 和 Demo Compose 保留现有拓扑。本轮未修改业务模型、认证接口或游戏逻辑。

## 生产 MongoDB 检查

仓库正式 Compose 使用 MongoDB 7.0.48 standalone，挂载命名卷并接入内部数据网。当前默认实例没有 MongoDB 身份认证，不能将网络隔离视作生产数据库认证。实际容器验证了源库只读备份、目标库 scoped `readWrite` 恢复、同库业务账号 `readWrite` 启动。正式环境仍需接入已启用认证的 MongoDB 或执行手册中的兼容迁移，并逐项验收。

standalone 的归档在暂停写入后运行，脚本要求确认该窗口。真实环境的调度、异地留存、age 私钥保管和 RPO/RTO 由运维落地。数据库授权账号、部署密钥、镜像和剧本发布物分别保管。应用恢复先使用备份对应版本和素材复验，后续升级按项目发布流程。

## 真实演练

使用两个独立、启用认证的 MongoDB 7.0.48 standalone 容器，官方 Database Tools 版本为 100.20.1。临时容器端口仅绑定 loopback。源库以合成账号创建配对，在合成发布的灯塔剧本里执行四次游戏操作。随后暂停源库业务访问，使用只读账号生成真实压缩备份，验证 SHA-256，用目标库 scoped 账号恢复到第二个实例的新命名空间。

比对结果为 **6 个集合的 BSON 文档和索引完全一致**，包含 2 个账号、1 个配对、1 个版本 4 的存档和 4 条嵌入回执。恢复后的应用通过 live/ready。原会话和新登录都能读取对应账号和房间，A 和 B 分别看到各自的线索和私聊。B 查询 A 的私有命令只得到未接受结果。A 重发同一 UUID 得到重复回执，存档保持版本 4，且无额外音效。

专项还覆盖空集合、归档结构与 gzip 损坏、SHA-256 和源库元数据变动、目录不可写、MongoDB 不可达、认证错误、未经选择目标及覆盖拒绝、正确和错误的 age 私钥、保留策略，以及匿名和只读权限边界。容器和合成产物由各自 fixture 清理。

## 复验命令

依赖 Docker、MongoDB 固定镜像、age、ShellCheck 和已锁定的后端开发依赖。在仓库根目录执行静态和编排检查。

```bash
docker pull mongo:7.0.48
for script in scripts/mongodb-*.sh; do bash -n "$script"; done
shellcheck -x scripts/mongodb-*.sh
TWOWORLDS_PUBLIC_HOST=localhost docker compose --env-file /dev/null config --quiet
docker compose --env-file /dev/null -f compose.demo.yml config --quiet
cd backend
uv run --locked pytest tests/mongodb_recovery.py -v -s --tb=short
```

- 恢复专项 **14 通过、0 失败、0 跳过**。ShellCheck、Bash 语法、Ruff lint、Ruff format、离线 uv lock 和 `git diff --check` 通过。
- 原后端完整 pytest 使用 SQLite 和真实 MongoDB 7.0.48，**1735 通过、0 失败、0 跳过**。有一条 Starlette/AnyIO 弃用警告。
- 前端 TypeScript、生产构建通过，Vitest **468 通过**。两套 Compose 配置均通过。
- 新增 CI 作业在托管 runner 中拉起独立的真实 MongoDB 源和目标，执行 ShellCheck 及恢复专项。托管结果以任务 PR 的 Checks 为准。

## 未执行的正式工作

公网部署、实际 DNS 与证书续期、真实 SMTP 和 AI、真正生产数据库认证迁移、正式数据备份、异地副本与实际负载的恢复时间均待审批和实测。本轮使用合成数据与虚拟凭据，未产生 SMTP 或 AI 服务费用。当前检查点为 T15.3 PR 人工审查。

建议从 [备份](../../scripts/mongodb-backup.sh) 读到 [恢复](../../scripts/mongodb-restore.sh)，再看 [真实数据演练](../../backend/tests/mongodb_recovery.py) 和 [运行手册](../../RUNBOOK.md)。
