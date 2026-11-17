# PR #27 正文

以下为本轮准备的完整PR正文；在线写入结果见交接文档。

游戏首次加载不会播放历史声音。玩家主动启用声音后播放当前环境音，状态型Cue只在新授权时播放；设备旋转/开关音则由服务端成功提交后的device_changed事件触发，避免“发现线索就响一次、真正重复操作反而无声”。T11.2只实现基础音频/字幕，不包含T11.3复杂演出、WS或AI。

实现与数据流：

- 原生AudioManager分Ambient/SFX/Voice通道，提供独立音量、全局静音/关闭、暂停/继续、环境音400ms淡变、旁白跳过/主动重播；后台、切档、登出、卸载取消请求并释放Blob URL。
- 复用当前角色presentation.cues与Bearer受保护媒体接口，保留no-store、MIME白名单和32MiB上限，无外部私有预载或URL Token。
- PR #27修复：服务端标记当前授权operation_sfx，将device_changed与对应角色Cue取交集，仅在CAS成功后返回audio_events(accepted_version/cue_id/asset_id)。接受版本来自既有唯一回执；连续不同实际操作各发声，同request_id重试、CAS输家、拒绝及首次恢复均不重播。
- 不发送原始事件、设备秘密值、伙伴隐藏信息；前端校验回执版本、Cue归属、SFX类型和重复事件。既有存档/回执格式、已发布剧本版本、谜题规则及媒体权限不变。
- 中文字幕使用服务端授权transcript/alt_text，支持独立显示/隐藏、16～28px字号、朗读区域与当前旁白关联。当前是整段中文，无实际说话人标注或逐句时间轴。

验证（Linux云环境）：

- 前端：npm run typecheck / test:unit / build / format:check，214通过（原203项完全保留，新增11），0失败/跳过。
- 后端新增操作音频14项：真实SQLite/Mongo各7项，覆盖连续操作、角色隔离、电源路由、双仓储CAS、成功提交后丢响应再确认。
- 音频/媒体/投影/存储专项首次261通过、1项默认断连镜像缺失；指定已有固定镜像后该项单独重跑通过。完整回归使用相同正确镜像配置：1198通过、4个基线失败、0错误/跳过。
- Ruff、99文件格式、git diff --check通过。没有修改或跳过既有前端测试、loader测试。
- 上一轮真实Chromium156、SQLite/Mongo双角色TCP WAV解码/播放检查均通过；本次新增证据为真实数据库HTTP与前端专项，不把模拟拒播当Safari实机验证。

复现命令（仓库根，Mongo使用本地测试实例）：

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run test:unit
npm --prefix frontend run build
npm --prefix frontend run format:check
TWOWORLDS_TEST_MONGO_IMAGE=mongo@sha256:884c055bff8b7144ca44830d01826facd3083b33c4dea44b94a1476c62de3c32 MONGO_URI=mongodb://127.0.0.1:27017 backend/.venv/bin/python -m pytest backend/tests -q --tb=short
backend/.venv/bin/python -m ruff check backend/src backend/tests
backend/.venv/bin/python -m ruff format --check backend/src backend/tests
git diff --check
```

第四项后端失败已完成同环境对照：PR目标acca4ed与PR分支61f2e19在同一CPython3.12.14/venv均失败，loader源码SHA256相同。3000层JSON在该构建上成功解析为list，随后Pydantic产生model_type ValidationError，loader映射成CONTENT_INVALID_SCHEMA，原测试期待CONTENT_INVALID_JSON。额外Linux3.12.4也在两分支失败，不能简单归因于3.12补丁版本差异；原Windows构建未复现。它是当前云环境下目标分支已有失败，非本PR新回归。完整堆栈见docs/reports/t11-2-json-baseline-evidence.md，未弱化测试。其余三项为未实现WS/NPC契约。

限制：

- 正式目录与正式音频素材尚未发布；合成TEST-ONLY WAV不是正式旁白或音乐，不声称版权/听感验收完成。
- Safari/iOS/Android真机、编码兼容与后台行为未实测；NotAllowedError模拟仅验证拒播处理。
- 操作事件是瞬时成功响应，没有持久化事件日志、跨设备可靠补送或伙伴操作音效追溯。提交成功但响应丢失后用原ID确认不补播一次性操作声音，避免推测/重放；现有状态型公开Cue仍可手动读取。逐句字幕、完整事件协议与复杂演出仍未完成。

建议阅读：domain/audio.py → domain/projection.py → application/audio.py → application/saves.py → frontend/services/game.ts与types/game.ts → audio-assets.ts → audio.ts → AudioControls/SubtitleDisplay。详细结果、复现和限制见docs/reports/t11-2-audio-subtitles.md的PR #27修复节。

本轮更新原PR #27后停止，等待人工审查，不自动合并，不进入T11.3。
