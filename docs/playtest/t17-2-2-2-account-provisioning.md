# T17.2.2.2 · 组织者预创建试玩账号

## 准备账号与运行环境

在组织者控制的 POSIX 主机运行。Windows 使用 WSL 的 Linux 文件系统。使用独立、启用身份认证的 MongoDB 实例和专用库，按 [Playtest 运行说明](t17-2-2-1-runtime.md#启动契约) 安全注入 `TWOWORLDS_PLAYTEST_MONGO_URI`、`TWOWORLDS_PLAYTEST_MONGO_DATABASE` 和 `TWOWORLDS_PLAYTEST_VERIFICATION_SECRET`。CLI 复用运行时的模式、库名、角色及匿名访问检查。部署人员仍需核对网络与实例隔离。CLI 无需网页 Origin 或内容发布目录，AI 与邮件分别沿用试玩的 `demo` 和 `disabled` 限制。

准备一个 UTF-8 JSON 文件，只包含已核准的测试别名。每个别名符合 `[a-z][a-z0-9-]{0,31}`，大小写和重复项都会校验。输入最多 16 KiB。用独立别名替代姓名、真实邮箱或手机号。例如为首轮三对分别分配账号。

~~~json
[
  "couple-01-a", "couple-01-b",
  "couple-02-a", "couple-02-b",
  "couple-03-a", "couple-03-b"
]
~~~

在仓库外创建由当前用户拥有的 `0700` 目录。选择未使用的输出文件名，整条路径使用实际目录，避免符号链接、团队共享盘及自动同步或备份目录。下面的命令假设已将获准别名清单保存到该目录。

~~~bash
install -d -m 700 "$HOME/twoworlds-playtest-credentials"
cd backend
TWOWORLDS_MODE=playtest uv run --locked python -m twoworlds.provision_playtest_accounts \
  "$HOME/twoworlds-playtest-credentials/approved-aliases.json" \
  "$HOME/twoworlds-playtest-credentials/batch-01.jsonl"
~~~

## 建号、凭据交付与登录

1. CLI 先检查整份输入、凭据落点、数据库安全和所有别名是否已存在。输入错误或已存在任一账号时，整批在写入前拒绝。
2. CLI 独占创建当前用户可读写的 `0600` 文件。按别名生成独立随机密码，先将凭据作为 `pending` 写入并落盘，再通过现有身份服务和 Argon2id 写入账号。数据库保存密码哈希和空会话列表。该建号路径从未签发初始化会话，无令牌等待撤销。
3. 每行 JSON 都带时间、批次和结果。按 `batch_id` 和 `alias` 匹配带凭据的 `pending` 行与随后的 `created` 行，只有匹配成功的凭据可交付。全部成功时末行是 `complete`，进程以 0 退出。退出码 1 表示批次失败或中断，2 表示命令参数错误。
4. 组织者在受控设备上读取私有文件，逐人通过独立安全渠道交付对应的 `email` 和 `password`。玩家在试玩站使用 `别名@playtest.invalid` 和初始密码登录，经现有 HTTPS 登录流程取得新会话。建号工具不会创建房间或配对。凭据文件只用于一次交付，核对分发后从组织者设备移除。初始密码作为玩家正常密码使用，凭据交付和文件删除均不会让密码或登录会话失效。

标准输出只包含结构化审计事件，字段为 UTC 时间、批次标识、结果及操作涉及的测试别名。配置错误以固定提示输出。仅凭据文件包含邮箱和明文初始密码，禁止把文件复制到 Git、聊天群、工单或普通日志。

## 失败恢复与试玩收尾

| 情况 | 处理 |
| --- | --- |
| 别名无效、重复，或预检发现已有账号 | 修正获准清单。核对已存在账号归属，禁止覆盖。此类预检失败不会写账号或创建凭据文件 |
| 路径不安全、已有文件或目录权限不符合 | 使用仓库外、无符号链接且由当前用户持有的 `0700` 目录，给新批次选择新文件名。保留旧文件供已授权的核对 |
| 模式、数据库权限或连通性检查失败 | 核对专用实例、认证及变量注入。CLI 不会回退到 Demo、SQLite 或正式库 |
| 批次中发现写入冲突或结果未知 | 工具停止，先前确认创建的账号保留。仅交付有 `created` 的同批次凭据。对 `conflict`、`unknown` 或只有 `pending` 的记录暂缓交付，先在隔离库核对该账号和凭据归属。禁止直接重跑旧批次或覆盖账号 |
| 写盘失败或进程中断 | 私有文件可能为空、部分成功或末行不完整，视为未完成。数据库与文件单独持久化，工具先落盘凭据再建号，进程可在数据库已提交但成功标记尚未持久化时退出。保留文件用于核对，仅以完整记录和明确结果为准 |

撤场时按[试玩隐私与同意说明](privacy-and-consent.md)和[准备度审计](t17-2-readiness-audit.md)执行。由授权维护人员停止试玩入口，按约定清理独立试玩库及其备份、日志和凭据文件。CLI 不提供删除、改密或批量回滚操作。数据库权限检查只能验证认证状态和作用域，独立实例和网络仍需在部署时验收。

## 阅读与验证入口

先看 [Playtest 配置与连接](../../backend/src/twoworlds/playtest.py)，再看 [CLI 输入、私有文件和建号流程](../../backend/src/twoworlds/provision_playtest_accounts.py)、[身份服务](../../backend/src/twoworlds/application/identity.py)及[集成测试](../../backend/tests/api/test_provision_playtest_accounts.py)。测试使用临时 MongoDB 容器和合成账号，通过真实应用路由核查空会话、登录及登出。

~~~bash
cd backend
uv run --locked pytest tests/api/test_provision_playtest_accounts.py tests/api/test_playtest.py -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv lock --check --offline
git diff --check
~~~
