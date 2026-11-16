# TwoWorlds 前端 · T10.1

当前只有身份入口：创建、恢复、启动验证、一次性恢复密钥确认和当前设备登出。Vue Router仅注册`/`。房间、邀请、书架、游戏、WS、PWA、音频和AI尚未实现，没有相应占位按钮。

## 本地运行

本轮实测Node **20.19.0**、npm **10.8.2**。依赖为精确版本，提交package-lock.json。Windows若`npm`命中异常的系统路径，使用已有`npm.cmd`；无需全局安装Vue或Vite。

```powershell
cd F:/two-worlds-agent-game/work/pr-t01-1-schema/frontend
npm.cmd ci --engine-strict --registry=https://registry.npmjs.org
npm.cmd run dev
```

开发服务仅绑定127.0.0.1，地址以Vite实际输出为准。本轮检查后已停止预览进程，不宣称有持续运行的演示或后端地址。当前可查看页面；**仓库后端没有独立TCP启动入口，不能完成真实HTTP身份联调**。不能把Vite页面可打开或单元测试的响应桩当成真实注册成功。

默认API与页面同源，路径是`/api/accounts`、`/api/sessions/recover`、`/api/me`、`/api/sessions/current`。未来有真实后端地址后，可在本地`.env.local`设置公开的`VITE_API_BASE_URL`，重启Vite；不得放密钥/token、用户名密码、query或fragment。没有硬编码生产地址或Vite代理，也不会自动启动或回退SQLite。跨源时后端必须显式允许前端Origin，不用Cookie认证。

## 调用与安全边界

`Identity.vue`校验表单 → `stores/identity.ts`调用类型化HTTP → `types/api.ts`白名单校验响应 → Store更新账号/会话 → 页面显示状态。

- session token仅在内存和sessionStorage的`twoworlds.session.token`保存，只有Bearer头携带，不进URL/日志，不用localStorage或自动持久化插件。
- recovery_key从创建动作返回到页面内存，**不在Pinia state、storage或URL中**。创建成功优先显示密钥；另在内存/sessionStorage用`twoworlds.recovery.pending=1`标记“未确认”，该标记只有状态，没有密钥。密钥展示期间注册beforeunload，确认保存清标记/密钥并移除监听，卸载也移除监听但保留pending以便刷新识别。复制失败保留可选择的只读文本，用户自行保存。恢复输入在请求结束后清空。
- 强行刷新后，密钥不会再显示或重新生成；即使me验证成功，也显示未确认警告及恢复限制。pending在me返回401时仍保留警告；成功恢复身份（已经持有密钥）或明确登出后清除。sessionStorage不可用时保留本页内存pending和离开保护，但不能承诺强行刷新后还能保留标记或找回密钥。
- 刷新后先GET `/api/me`；401清除本地身份，网络/503保留未验证token并提供手动重试。服务器决定会话是否有效，本地时钟只负责显示到期时间。
- 登出成功204才清理；网络错误保留当前身份并提示撤销未确认。401说明会话已失效，清除本地状态。
- 创建结果不明不会自动重试，提示“服务端可能已创建”；未收到密钥的匿名身份无法承诺找回。
- HTTP使用`cache: no-store`、`credentials: omit`、拒绝重定向；超时覆盖取响应和解析正文。保留status/code/retryable，但以安全本地文案显示错误，不回显原始异常或正文。
- sessionStorage不可用时仅保留内存会话并明确提示刷新可能需恢复，不降级为localStorage。sessionStorage不是防XSS的保险箱，本轮未声称完成生产安全部署。

## 验证与学习

```powershell
npm.cmd run typecheck
npm.cmd run test:unit
npm.cmd run build
npm.cmd run format:check
```

初次交付40项，PR #23审查修复后为**68项通过**：HTTP35、Store15、页面18；本次类型检查、生产构建、格式检查全部通过，未删除/skip/弱化原40项。历史干净安装、后端身份30项与1440/390px布局结果仍保留为初次交付证据，本次未重跑后端，不冒称完整回归。单测用响应桩验证前端逻辑，不替代实际前后端联调。

本次Edge CDP额外验证原生beforeunload弹窗：取消离开后仍持有密钥，确认后不再弹出，继续刷新后显示pending警告且不重新创建身份。浏览器检查的API仍是明确响应桩。原生弹窗需要用户交互，移动端系统终止等情况不保证触发，页面不能自定义浏览器提示文字；详见[MDN](https://developer.mozilla.org/en-US/docs/Web/API/Window/beforeunload_event)。它是降低误操作风险的提醒，不是密钥备份。

HTTP路径必须是`/api/`加一个或多个后端Identifier段（每段`[a-z][a-z0-9_]{0,63}`），允许pair_123/save_123，拒绝穿越、query、fragment、编码字符、重复/尾随斜杠、换行或非API路径。非法路径在fetch之前拒绝，未增加任何房间或存档业务。

官方npm审计：生产依赖0项；开发依赖4项moderate，经js-beautify的glob/minimatch/editorconfig链引入。为兼容本机Node20，Vue Test Utils使用2.4.6；其最新版2.6引入了要求更高Node版本的依赖。本轮没有强行跨主版本覆盖依赖来消除审计输出，开发依赖问题保留在报告中，不宣称全部依赖无漏洞。

阅读顺序：`src/types/api.ts` → `src/services/http.ts` → `src/stores/identity.ts` → `src/views/Identity.vue` → 三份测试。把创建成功当作具体例子：响应里的token进入Store，恢复密钥只交给页面；点击“我已保存，继续”后页面清掉密钥，仍以原会话显示身份。

全部命令、工具版本、红测和限制见[本轮报告](../docs/reports/frontend-identity.md)。下一环节T10.2为房间与书架；本轮完成后停止，须用户明确继续。
