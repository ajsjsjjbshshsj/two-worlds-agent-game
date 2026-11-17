B给灯塔供电后，A手动读取相邻确认版本会看到电路点亮/时钟箱通电；A打开回声闸后，B手动读取会看到声呐就绪与三道扩散波。动画结束、取消或失败时始终显示服务器确认的最终状态，动画不决定规则成功。

本轮仅T11.3.1：

- 从fetch后的最新codex/bootstrap=c31aa9e创建分支，Git合并提交及父提交确认PR #27已合并。
- 新增可复用CausalPerformance与原生Web Animations播放器，按save/pair/script/version/role、接受版本、演出id与页面generation去重隔离。
- 初次读档仅基线，相同版本不重播，版本跳跃直接显示最终状态。切档/角色/剧本/凭证/离页/后台/减少动态取消旧轨道；旧HTTP读取沿用game Store校验，旧动画完成/异常不能覆盖新演出。
- 仅消费个人visual_state.clock_powered/echo_available，不读伙伴设备或匹配observations文案；沿用T11.2 AudioManager与授权audio_events，不补造操作声音。
- 保持原214项测试和后端/存档/依赖/锁文件不变，补充报告、任务清单、验收与交接。

验证：

- 前端251通过（原214保留、新增37），0失败/跳过；npm run typecheck/test:unit/build/format:check通过，git diff --check通过。
- 真实SQLite/TCP+Chromium156双角色，用页面操作提交B供电/A开闸并手动读取，分别启动2/4条原生动画；结束静态、初次/重复/跳版本、减少动态、权限投影、小屏390px无溢出通过，0音频响应、0页面异常。
- 关闭声音/动画或图片失败不影响确认状态和操作；音频启用但仅echo_available变化时不制造power_switch操作音效。
- 未修改后端，本轮未执行Mongo/后端回归；正式资源仍空，浏览器使用隔离TEST-ONLY透明PNG验证SVG原型。

限制：只完成两个短反馈，不是完整T11.3。未实现其他合作节点、可跳过关键剧情/复杂转场、WS/NPC/AI、持久事件日志。正式美术/音频/版权/媒体分层、听感及Safari/iOS/Android真机仍未验收，不标完整QA-M01～M07通过。

阅读顺序：frontend/src/services/causal-performance.ts → performance-animation.ts → components/game/SceneRenderer.vue → LighthouseScene.vue/StarlineScene.vue → tests/causal-performance.spec.ts与performance-scene.spec.ts。复现命令与临时TEST-ONLY页面观察步骤见docs/reports/t11-3-1-causal-performance.md。

完成后停止等人工审查，不自动合并，不进入T11.3.2。
