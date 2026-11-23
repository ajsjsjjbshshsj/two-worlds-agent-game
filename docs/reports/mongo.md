# T16.2 · MongoDB 持久化、服务恢复与备份恢复

## 环境

- 本机：Docker Desktop 容器 `twoworlds-mongo`，MongoDB 8.0.34，仅绑定 127.0.0.1:27017；每次 e2e 使用随机命名隔离库（`t16_<hex>`），演练使用 `t16_src_*` / `t16_dst_*` 随机库并在结束后删除。未触碰任何生产数据库。
- CI：`mongo:7.0.48` service（backend-tests、acceptance-e2e）与 database-recovery job 的独立认证容器。

## 已执行与结果

| 项目 | 方式 | 结果 |
| --- | --- | --- |
| Mongo 启动与连接 | 容器健康检查 + `ping` + 应用启动 | 通过 |
| 注册/登录/建房/存档写入 | 双浏览器 e2e（mongo 运行） | 15/15 通过 |
| 游戏状态与回执写入 | 同上（含并发与幂等重放） | 通过 |
| 服务重启后数据恢复 | e2e 终止 API 子进程并以同一 Mongo 库重启；双方重连继续提交至通关 | 通过 |
| 玩家重连与双方一致 | 断网/刷新/重启后版本收敛断言 | 通过 |
| 备份→校验→恢复到独立新库 | `backend/tests/t16_backup_restore.py`（docker exec 官方 mongodump/mongorestore） | 1/1 通过 |
| 恢复不覆盖原库 | 恢复前后源库逐文档相等断言 | 通过 |
| 恢复后私密隔离 | 恢复库上重新做角色投影，A 私有线索不出现在 B 投影 | 通过 |
| 认证/只读备份角色/损坏拒绝/保留策略/age 加密 | CI `database-recovery` job（`tests/mongodb_recovery.py`，Linux） | 由 CI 执行（PR #52 已合并运行；本 PR Checks 复核） |

## 本地备份恢复演练步骤（t16_backup_restore.py）

1. 经真实服务向源库写入账号、房间、存档与一条已接受回执。
2. `docker exec mongodump --archive --gzip` 导出压缩归档；写入 `source-db` 与 `SHA256SUMS`（SHA-256）。
3. 校验归档哈希与解压内容包含源库名。
4. `docker exec -i mongorestore --archive --gzip --nsFrom <src>.* --nsTo <dst>.*` 恢复到**不同**的新库。
5. 逐集合逐文档比较源/目标；源库恢复前后完全相等。
6. 在恢复库上重建 SaveService 投影，验证角色私密隔离仍成立。

## 已知限制

- 生产 bash 包装脚本 `scripts/mongodb-*.sh` 依赖 Linux 的 `flock`/`stat -c`/`realpath -e`，**无法在 Windows 原生运行**；其完整行为（含认证、只读角色、损坏拒绝、保留轮换、age 加密与错误身份拒绝）由 CI ubuntu 的 `database-recovery` job 覆盖。本地演练用官方 Database Tools 直接完成同等实质检查。
- 本机未安装 `age`（下载被网络阻断），age 加密用例本地未执行，标记为 CI 覆盖。
- 单机 standalone 验证；复制集切换、分片、跨主机恢复、备份加密密钥管理未验证。
- 恢复演练为逻辑一致性验证，未做恢复后长期运行与性能基准。