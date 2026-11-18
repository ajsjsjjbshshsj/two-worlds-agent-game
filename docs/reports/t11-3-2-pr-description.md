T11.3.2在服务器确认的个人快照上补齐合作反馈：每个剧本各3处合作节点，以及1段可跳过的关键演出。保留T11.3.1的供电和声呐就绪动画，首读、重读和跳版本直接显示确认的最终画面。

## 实现与数据流

- 灯塔：B看到光束聚焦；B供电后A看到通电；A维修后本人看到机械启动、B看到航道就绪。维修的两个视角计为同一合作节点。
- 星轨：A开闸后B声呐就绪；扫描后双方看到授权定位；安装后双方看到导轨连接。
- 确认的个人presentation.visual_state及public.ending → CausalPerformance相邻版本/范围/场景检查 → SceneRenderer nextTick → 原WAAPI播放器；Vue始终按确认快照渲染最终状态。
- 仅允许survey→boarding的导轨连接、decision→completed的已知公开结局跨场景触发。沿用save/pair/script/script_version/role、凭证、版本和页面generation隔离、AbortController和异常清理。
- 灯塔guide_now/wait_tide呈现光束或潮汐；星轨rescue_detour/return_station呈现救援支线或归站。约3.2秒，原生“跳过演出”按钮支持键盘/触屏，固定视口角落；跳过立即取消视觉轨道，无命令/POST/存档版本变化，不阻断游戏。
- 后台、pagehide、卸载、切换范围/凭证、减少动态或部分动画失败均清理轨道。静态最终画面不依赖动画完成。

只使用已有授权个人投影，未修改后端、规则、存档、已发布剧本、AudioManager/audio_events/operation_sfx、字幕生命周期或依赖；不读取伙伴私有设备、不解析中文、不推测/补播音效。

## 本地验证

frontend目录运行：

```bash
npm run test:unit
npm run typecheck
npm run build
npm run format:check
```

- 328项通过，0失败/跳过，19个测试文件；原251项文件/断言未改，新增77项（协调器36、场景41）。
- typecheck、build（88 modules）、format及根目录git diff --check通过。
- 后端未改，本轮未跑后端/SQLite/Mongo单测回归；下面的真实SQLite浏览器证据不替代这些单测或Mongo验证。

## 真实浏览器证据

系统Chromium156，真实SQLite/uvicorn TCP+Vite，4个独立双角色页面流程覆盖两个剧本各自的两个结局。新增操作与投票通过真实UI提交，搭档手动读取个人快照；没有改数据库或伪造规则状态。

新增合作节点、双方权限隔离、键盘Enter/触屏tap跳过、无额外POST及版本/结局不变、正常结束静态画面与服务端回顾一致均通过。另验证首读/重读/刷新、跳版本、减少动态；390px无溢出、跳过按钮至少44px且处于视口内、0未处理页面异常、声音关闭时0音频响应。不是单元测试截图或Safari/iOS/Android真机验收。

隔离TEST-ONLY发布库使用合成透明PNG/测试WAV，正式资源未发布；临时脚本、截图、数据库均被忽略，不进入提交。测试详情和观察方法见[开发报告](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/blob/codex/t11-3-2-cooperative-performances/docs/reports/t11-3-2-cooperative-performances.md)。

## 限制与审查范围

仍是原创SVG/WAAPI原型；正式美术/音频/媒体分层/素材许可、人工视听验收和Safari/iOS/Android真机仍待独立完成，QA-M01～M07未整体标通过。无历史演出重看、实时同步/WS、可靠事件补送。本轮未开始T11.3.3或T12，未使用子代理，禁止自动合并。

## GitHub 交付与 CI

首次执行 `gh pr create` 时曾返回 `Forbidden`。GitHub API 访问后来恢复，已直接读取 PR #29 和检查记录。

[PR #29](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/29) 已成功创建，状态为 OPEN，尚未合并，等待人工审查。base 为 `codex/bootstrap`，head 为 `codex/t11-3-2-cooperative-performances`。

上一轮文档修订前的 HEAD 为 `a2f79ef65ee844305576d2548d6ad5e2b51951a8`。该轮修订推送后，GitHub 确认 PR HEAD 为 `4d5777c450aa97ad07237b15bb6f05611459012c`，本轮以此为核对基准。最新提交见 [PR 提交页](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/29/commits)。

直接通过 GitHub API 查询提交 `4d5777c450aa97ad07237b15bb6f05611459012c`，结果为 check-runs 0、workflow-runs 0、commit statuses 0。该提交没有可报告的 GitHub CI 运行结果。328 项通过来自 T11.3.2 的本地前端测试。

## 建议阅读顺序

1. frontend/src/services/causal-performance.ts：范围、相邻版本、明确跨场景和skip。
2. frontend/src/services/performance-animation.ts：临时轨道、取消与部分失败清理。
3. frontend/src/components/game/SceneRenderer.vue：生命周期、按钮与动画挂接。
4. LighthouseScene.vue / StarlineScene.vue：服务器确认的静态最终状态与动画目标。
5. frontend/tests/cooperative-performance.spec.ts / cooperative-scene.spec.ts：新77项行为验证；原有测试完整保留。
6. docs/reports/t11-3-2-cooperative-performances.md：设计、真实浏览器证据、限制及自行观察步骤。
