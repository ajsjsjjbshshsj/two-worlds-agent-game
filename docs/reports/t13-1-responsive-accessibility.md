# T13.1 · 响应式布局、触控与无障碍

日期：2026-11-22。基线 `11fc04336cf41566c155d74b1eff91cdf610f5b4`，PR #40 已合并。任务分支 `codex/t13-1-responsive-accessibility`。本轮只做前端适配；T13.2 PWA 与 T16 真机验收仍未实施。

## 设计与文件职责

沿用现有 Vue 组件和 CSS。小于 768px 使用单栏，768～1023px 使用收缩安全的双栏，1024px 起保留桌面留白及双栏。小于等于 430px 的验证码输入和发送按钮上下排列。长标识与长观察文字允许换行，Grid 子项使用 `min-width: 0`，没有隐藏关键功能或用横向裁切掩盖溢出。

| 文件 | 职责 |
| --- | --- |
| `frontend/src/styles/main.css` | 断点、最小控件尺寸、换行、焦点、输入字号、安全区域和分区导航 |
| `frontend/src/views/Game.vue` | 场景/进度回执/行动/设备线索/声音的页内入口；行动在 DOM 中先于长篇信息，桌面与键盘顺序一致 |
| `frontend/src/components/SpaceShell.vue`、`views/Identity.vue` | 跳过导航；账号区可聚焦；邮箱输入模式、大小写和拼写提示 |
| `frontend/src/composables/keyboard-viewport.ts`、`App.vue` | 挂载一次的可视区域监听，只在已聚焦表单控件被遮挡时滚动，卸载移除监听和排队帧 |
| `frontend/src/components/game/Device.vue`、`device-labels.ts` | 有名称的设备焦点目标；中文设备名称和标识并存；布尔状态用“开启/关闭”文字 |
| `frontend/src/components/game/SceneRenderer.vue` | 热点关联设备目标，演出跳过按钮回到文档布局中，避免悬浮遮住操作 |
| `frontend/src/components/game/ActionPanel.vue` | 禁用时提供可读的连接/进度/待确认提示 |
| `frontend/index.html` | `viewport-fit=cover` 配合安全区，保留浏览器缩放能力 |
| `frontend/tests/accessibility.spec.ts` | 6 项行为回归测试 |
| `frontend/e2e/mobile_layout.py` | 本机已有 Python Playwright 驱动真实 Edge，显式 TEST-ONLY HTTP/WS 夹具 |

例如用户触摸发射器热点，只会聚焦并滚动到本人投影内的设备详情。用户仍在原行动表单选择角度，提交继续走原 Game Store、UUID 持久记录和服务器命令。只有收到原服务确认流程接受的快照才更新画面；本轮没有添加客户端规则、修改音频协调器或更换会话机制。

## 验证命令与结果

Windows 本机：Node `20.19.0`、npm `10.8.2`、Playwright `1.62.0`、Edge `158.0.4370.33`。

```powershell
cd frontend
npm.cmd ci --engine-strict
npm.cmd run typecheck
npm.cmd run test:unit
npm.cmd run build
npm.cmd run format:check
# 第一个终端启动 Vite，第二个终端执行浏览器矩阵
npm.cmd run dev -- --port 5193 --strictPort
python e2e/mobile_layout.py
# 项目根目录
git diff --check
```

`python` 使用已有安装的 Playwright，未修改全局环境或项目依赖。默认选择本机 Edge；其他已安装 Chromium 通道可通过 `LAYOUT_BROWSER` 指定。`LAYOUT_BASE_URL` 可指定实际启动的本机 Vite 地址。该浏览器脚本不启动或连接业务数据库，API 和 WebSocket 响应均为显式测试夹具，不能据此声称完成数据库或真实认证集成。

| 检查 | 实际结果 |
| --- | --- |
| TypeScript strict | 通过 |
| Vitest | 434 通过，0 失败；原有 428 项保留，新增 6 项 |
| Vite production build | 通过 |
| Prettier format check | 通过 |
| 浏览器矩阵 | 154 个检查场景通过，0 页面异常 |
| Git diff 检查 | 通过 |
| GitHub CI | PR 创建后检查实际运行结果；PR Checks 为最终证据，不以本机测试代替 |

测试先复现了四项具体失败：遮挡字段未滚动、缺少跳过入口、设备缺少命名焦点目标与文字状态、邮箱缺少输入提示。随后实现并复验。新增测试还覆盖无 VisualViewport 时的降级、非表单焦点不滚动、卸载取消帧与移除监听。

## 浏览器矩阵与无障碍证据

七种竖屏/桌面尺寸，每种 22 个检查场景：

| 尺寸（CSS px） | 场景数 | 结果 |
| --- | --- | --- |
| 320×568 | 22 | 通过 |
| 375×667 | 22 | 通过 |
| 390×844 | 22 | 通过 |
| 430×932 | 22 | 通过 |
| 768×1024 | 22 | 通过 |
| 1024×768 | 22 | 通过 |
| 1440×900 | 22 | 通过 |

每组包括登录错误与焦点、注册、找回密码、房间列表、邀请生成、加入确认、书架、两剧本八个阶段、待确认命令、刷新后查询原 UUID、双方设备控件、可跳过结局演出、放大文字与横屏。窗口总宽度无阻断性溢出，可见按钮/链接/输入/选择框/summary 的边界至少 44×44px，表单输入都有标签。触屏尺寸通过真实浏览器 tap 操作热点与跳过按钮，桌面通过 click；确认提交产生一次夹具命令请求并保留预期版本。

键盘 Tab 可以访问跳过入口，回车聚焦目标区域；热点聚焦设备后存在可见轮廓。取消清除待确认记录的浏览器原生确认后，焦点仍留在原按钮。错误和同步状态沿用 alert/status，额外提供禁用原因文字。除专门检查演出的分支外，矩阵使用 reduced-motion，动作表单仍可用。书架放大文字及宽高互换后仍可操作，桌面书架保持双栏。截图包含压力测试长文字，均为 TEST-ONLY 内容。

图片/音频的真实授权、清理、去重继续由现有测试覆盖，本轮未改变相关服务。字幕处于普通文档流，控制按钮换行，演出按钮不再固定覆盖窗口底部。正文、金色焦点及浅色状态沿用既有深色配色。本轮没有进行完整 WCAG 认证或屏幕阅读器实机测试。

## 审阅截图

- [手机注册](../assets/t13-1/phone-identity.png)
- [手机灯塔游戏、行动、长线索与字幕](../assets/t13-1/phone-game.png)
- [平板书架](../assets/t13-1/tablet-library.png)
- [桌面星轨双栏](../assets/t13-1/desktop-game.png)

浏览器原始结果写入本机忽略的 `frontend/test-results/t13-1/results.json`，不上传临时记录、浏览器配置、构建产物或任何真实凭证。

## 限制和下一环节

- **iPhone Safari、Android Chrome、iPad、macOS Safari 及手机软键盘真机未验证**。本机 Edge 的触摸/尺寸模拟不替代这些设备。
- 软键盘逻辑用 VisualViewport 行为测试验证；刘海与手势安全区域使用 CSS env，实际设备的遮挡、横屏、输入法与浏览器缩放仍留 T16。放大文字测试不是原生浏览器工具栏缩放的完整验收。
- 正式图片、音频及许可未补齐；截图是现有 SVG 原型和测试内容，不代表正式素材发布。
- 本地未重跑后端全量，后端生产代码完全未改；既有完整后端/真实 Mongo 检查保留在 GitHub CI。
- T13.2 的安装、manifest、Service Worker、离线外壳与缓存隔离未开始。下一轮可先定义静态外壳白名单并测试 API/WS/受保护媒体绝不入缓存。

本环节交付后停止，等待用户审查 PR，不自动开始 T13.2。
