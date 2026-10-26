# TwoWorlds 实施方案 · 2026-10-26

> 历史材料提示：完整聊天补读后已新增 [v0.2 项目文档入口](../../../README.md)。本文件是迁入的初步草稿，身份、幂等命名空间、动作参数和两剧本玩法均需按新提案核对；不作为直接编码的最新任务单。

> 初步技术草稿。完整审阅版以 `outputs/TwoWorlds-项目设计与实施计划.md` 为准，尤其是恢复密钥与有期限登录会话分离、邀请有效期和剧本版本设计。当前仅有测试草稿，尚未实现或验证可运行平台。

目标：两台设备用各自身份进入同一故事，看到不同线索，通过确定性机关合作通关。关闭浏览器、切换设备、重启服务后可恢复。

## 仓库审查

参考仓库： https://github.com/ajsjsjjbshshsj/philoagents-course ，审查版本 `211033c6785c29cbe79e053ebc5f3219e5f0051f`。
已读取 README、pyproject、infrastructure/api.py、session.py、conversation_service/workflow/graph.py、generate_response.py。

- 可借鉴：API / application / domain / infrastructure 分层，LangGraph 编排，Mongo 持久化，WebSocket 首帧认证，图实例复用。
- 现有 UI 是 Phaser/JavaScript；新建 Vue 3 + TypeScript PWA 更适合手机和桌面共用。
- 现有 `/session` 接受客户端提供的 player_id 并签发身份；源码也明确其没有账户所有权保障。不能直接用于云端情侣存档。
- 现有图以 player_id:philosopher_id 划分会话，没有情侣、剧本、局次、角色权限或确定性状态机。
- 原仓库未提供本需求的双人事务、私有线索投影、幂等并发提交或重连协议。此处重新实现业务层，未复制其游戏素材或源码。

## 方案选择

1. **采用：Vue PWA + FastAPI 模块化单体 + MongoDB**。最小部署单位少，单文档 CAS 保证局内原子性；数据库轮询推送支持跨 worker，适合首版。
2. 在原 Phaser UI 上扩展：视觉游戏基础可复用，但移动端和业务交互改动大。
3. 从首版拆分实时服务、队列和 AI worker：扩展性更好，但当前增加部署与一致性成本；后续有负载数据再拆。

## 数据与权限

- 首版匿名身份由服务器生成 256 位恢复密钥；数据库仅保存其 SHA-256 摘要。密钥就是个人账户凭证，跨设备输入后恢复原身份。没有邮箱或第三方登录，丢失密钥无法恢复；后续升级可撤销的登录会话。
- 情侣房间由创建者占 A 位，128 位邀请凭证只能填入唯一 B 位。加入用 CAS 防止第三人挤入；不允许客户端指定成员身份。
- 每个房间每个剧本一个独立存档，`pair_id + script_id` 唯一；独立版本、剧情、双方私有对话、操作回执。
- 所有 HTTP、WebSocket、语音能力入口先鉴权、验证房间成员身份，再投影当前角色可见的数据。HTTP 与 WS 都不返回对方私有线索、操作回执或内部谜底。

## 提交和恢复协议

`POST /api/saves/{id}/commands` 接收 `{request_id: UUID, expected_version: int, kind, value}`。
先按用户与请求 ID 检查回执；相同 ID 不同内容返回 409；再验证版本、角色、前置条件。所有状态、对话和回执一起 CAS 写入单一文档。
同版本并发写只有一次成功；失败返回 409，客户端刷新后由用户重试。网络失败保留原命令 ID，可重发确认，禁止自动生成新 ID 重放不确定操作。
首版每档最多 512 次已接受命令；达到上限显式拒绝，避免无限文档或静默丢弃幂等记录。对话仅保留每人最近 20 轮，事件最近 30 条。

WS 用首帧发送凭证（10 秒超时），每 250ms 查询存档修订，只发送当前玩家投影；每 10 秒发送心跳快照。完整快照无需事件重放，重连后直接替换旧状态。浏览器指数退避并加抖动，恢复前禁用操作；HTTP 定时补偿用于推送故障。禁止缓存 API/WS 或离线提交。

## 规则和 AI 边界

两套内置原创短剧本：跨时灯塔、末班星轨。A 阅读编码并分享，B 用编码操作机关；B 阅读坐标并分享，A 用坐标完成联动。双人就位和角色前置条件由纯 Python 引擎验证。

LangGraph：整理当前玩家投影 → 生成 NPC 对话或场景补充 → 文本约束。没有状态修改工具，模型永远拿不到伙伴未分享线索或内部答案。模型输出不决定通关、不添加可执行线索。默认本地示例回复，可配置 DashScope 兼容接口；超时或格式异常回退示例并显示状态。不在开发测试中调用付费模型。

语音预留 Python Protocol（VoiceRoomProvider / SpeechProvider）和成员鉴权后的 capability 端点；未配置时明确 disabled。不申请麦克风、不伪造 LiveKit token。后续由适配器签发短期 room-scoped token，接入 WebRTC/LiveKit 和流式 ASR/TTS。

## 界面

中文、夜蓝/雾蓝/暖金。桌面为剧本书架 + 当前章节 + 私人线索/对话；手机单列。标志性视觉为两条通向同一灯塔的光线，用 CSS/SVG 绘制。真实显示同步、重连和存档版本，不把房间成员状态伪装成在线状态。

## 执行任务与验收

- [ ] 1. 编写规则、权限、恢复、并发、幂等和 AI 隔离测试，运行确认缺失实现。
- [ ] 2. 实现 domain、repository、service、API。SQLite 演示和 Mongo 共用仓储契约；测试完整通关、重启恢复、跨档隔离、两人争抢房位。
- [ ] 3. 实现 Vue PWA，密钥恢复、房间邀请、多剧本独立进度、角色操作、NPC 对话和重连。执行 TypeScript 检查与生产构建。
- [ ] 4. 用真实 Chromium 两个独立浏览器上下文测试完整流程、刷新、断线、存档隔离和窄屏；保存截图。
- [ ] 5. 提供 Docker Compose、反代和部署说明、CI、Mongo 真库契约测试、可复制运行步骤；记录实际通过和未验证项目。

## 部署策略

本机 Docker daemon 未启动，先使用 SQLite 文件演示，不以此冒充 Mongo 验证。生产必须显式设置 Mongo URI 和精确允许的 Origin，不允许降级 SQLite。Web 与 API 同域，TLS 由入口终止，WS Upgrade 透传，数据库不发布端口，凭证由环境变量提供。原子性依据：https://www.mongodb.com/docs/manual/core/write-operations-atomicity/ 。

演示不等于公开上线：上线前需要实际云 Mongo 冒烟、恢复演练、边缘频率限制、身份撤销、访问日志脱敏、HTTPS 及真机 iOS/Android 验证。模型生成内容仍须产品评估；权限隔离不能防止模型猜测或编造，应清楚标注 NPC 文本不构成机关规则。
