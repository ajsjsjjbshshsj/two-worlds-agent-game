# Windows 本机双浏览器试玩指南（T17.2.3.1）

本指南使用**本地 Demo 模式**：Vue 前端 + FastAPI + SQLite + demo AI + console 邮箱验证码。只监听 `127.0.0.1`，不连接外部 AI、不发送真实邮件、不连接正式 MongoDB。页面会明确显示“本地试玩版 · 合成占位素材 · 非正式发布内容”。

> 本轮不是阿里云部署、不是公网 Playtest、不代表正式素材验收。合成图片与音频仅用于在本机体验完整玩法。

## 1. 准备 Docker Desktop

1. 安装并启动 Docker Desktop，确认右下角引擎为 Running。
2. 在 PowerShell 验证：

```powershell
docker version
docker compose version
```

3. 获取**包含 PR #59 的代码**。先打开 [PR #59](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/59) 查看状态，再按下面两种情况**二选一**：

   **情况 A：PR #59 尚未合并（使用 PR 分支）**

   ```powershell
   git clone https://github.com/ajsjsjjbshshsj/two-worlds-agent-game.git
   cd two-worlds-agent-game
   git fetch origin
   git switch codex/t17-2-3-1-local-playable-demo
   git pull --ff-only
   ```

   **情况 B：PR #59 已经合并（使用主分支）**

   ```powershell
   git clone https://github.com/ajsjsjjbshshsj/two-worlds-agent-game.git
   cd two-worlds-agent-game
   git fetch origin
   git switch codex/bootstrap
   git pull --ff-only
   ```

   已有本地仓库时跳过 `git clone` 与 `cd`，进入项目根目录后执行 `git fetch origin`，再选择对应的 `git switch` 与 `git pull --ff-only`。

   两种情况下都执行一次代码存在性校验；第一条命令必须成功，第二条输出当前提交：

   ```powershell
   git ls-files --error-unmatch backend/src/twoworlds/demo_content.py
   git log --oneline -1
   ```

   如果 `git ls-files` 报错，说明当前分支不包含 PR #59 的 Demo 实现，**不要继续执行试玩步骤**；未合并时切到 `codex/t17-2-3-1-local-playable-demo`，已合并时切到 `codex/bootstrap` 并重新拉取。

## 2. 生成本地合成试玩内容

内容生成需要 Python 3.12 与 uv（只生成一次；以后代码未变可跳过）。在项目根目录：

```powershell
uv sync --project backend --locked
uv run --project backend --locked python -m twoworlds.demo_content .local-demo-content
```

预期输出：

```text
Local demo content ready: ...\.local-demo-content
LOCAL DEMO ONLY - SYNTHETIC TEST-ONLY - NOT FORMAL PUBLICATION
  lighthouse 1.0.0: 28 synthetic assets
  starline 1.0.0: 25 synthetic assets
```

该目录已被 `.gitignore` 排除，**不要提交到 Git**。生成器读取真实剧本规则，生成合成 PNG/WAV、SHA-256、test-only 审核记录与完整性清单；不会修改正式剧本 JSON 或正式发布注册表。

需要重新生成时：

```powershell
uv run --project backend --locked python -m twoworlds.demo_content .local-demo-content --force
```

`--force` 只替换带本生成器完整性标记的目录；不会删除普通用户目录。

## 3. 启动 TwoWorlds

在项目根目录：

```powershell
docker compose -f compose.demo.yml up -d --build
docker compose -f compose.demo.yml ps
```

首次构建需要下载基础镜像并安装依赖，可能数分钟。启动后：

- 游戏页面：<http://127.0.0.1:8080>
- 后端 API（经前端同源 `/api` 代理）：<http://127.0.0.1:8080/api/scripts>
- 直接后端端口（仅排障）：<http://127.0.0.1:8000/api/scripts>

两个端口都只绑定回环地址，局域网其他设备不能直接访问。Demo 前端通过同源 `/api` 代理访问后端，避免 `localhost` 与 `127.0.0.1` 跨站导致会话 Cookie 无法发送。

## 4. 注册两名玩家

使用两个独立浏览器配置（例如 Chrome 普通窗口 + Edge 窗口，或 Chrome 普通 + 无痕窗口）。**不要在同一窗口切换账号**，以保证 Cookie/存储独立。

### 玩家 A（Chrome）

1. 打开 <http://127.0.0.1:8080>。
2. 切换到“注册”，输入邮箱、密码、昵称，点击“发送验证码”。
3. 在 PowerShell 查看本机控制台验证码：

```powershell
docker compose -f compose.demo.yml logs -f backend
```

找到 `[dev-email] to=你的邮箱 purpose=register code=123456`，输入验证码并完成注册。

### 玩家 B（Edge 或无痕窗口）

1. 打开同一个 <http://127.0.0.1:8080>。
2. 用另一个邮箱重复注册。验证码同样在 backend 日志中。

console 验证码只用于本机 Demo，不会发送真实邮件。

## 5. 创建房间与邀请

1. A 登录后点击“创建新房间”，进入房间页。
2. 复制页面上的邀请链接（形如 `http://127.0.0.1:8080/pairs#invite=...`）。
3. B 在独立浏览器打开该链接，登录后点击“确认以当前身份加入 · 角色 B”。
4. 双方进入同一房间的“剧本书架”。

## 6. 双人游戏

1. 双方选择《跨时灯塔》或《末班星轨》并进入。
2. A/B 角色由服务端分配；各自只看到自己的私有线索、设备与观察。
3. 按页面行动卡操作设备、分享线索、观察搭档操作带来的因果变化。
4. 双方提交行动后等待服务端确认；实时状态通过 WebSocket 同步。
5. 结局需要双方投票一致；分歧后可改选。
6. 完成后返回书架，选择另一个剧本验证互不干扰。
7. 刷新页面或重新登录，继续原存档。

如果页面提示连接中断，点击“重新连接”；服务端确认前不会改变世界。断线期间搭档仍可推进，恢复后读取权威进度。

## 7. 服务重启与存档保留

```powershell
docker compose -f compose.demo.yml restart backend
```

SQLite 数据位于命名卷 `sqlite_data`，重启容器后账号、房间、剧本进度与回执仍保留。刷新页面重新连接即可。

## 8. 停止服务与删除存档

停止但**保留存档**：

```powershell
docker compose -f compose.demo.yml down
```

**警告：以下命令会永久删除本机演示账号、房间和全部存档：**

```powershell
docker compose -f compose.demo.yml down -v
```

只在明确要清空重玩时使用。删除后重新注册两个账号即可。

## 9. 常见问题

- **页面打不开**：确认 Docker Desktop 已启动、`docker compose ps` 两个服务均为 Up；确认访问 `127.0.0.1` 而不是局域网 IP。
- **端口被占用**：关闭占用 8080/8000 的程序，或停止旧容器后再启动。
- **提示发布目录无效**：先执行第 2 步生成 `.local-demo-content`，再启动 Compose。
- **收不到验证码**：这是 console 模式；用 `docker compose logs -f backend` 查看，不需要真实邮箱。
- **邀请链接打不开**：确认 B 使用同一地址 `127.0.0.1:8080`，并在登录后打开链接。
- **隐私异常**：本 Demo 与正式环境使用相同的角色投影和权限规则；如发现越界请停止试玩并记录复现步骤。

## 10. 边界声明

- 只允许本机浏览器；未开放公网/局域网端口。
- 合成占位素材不是正式美术/音频，不能对外发布。
- demo AI 不调用外部 Provider；不需要 API Key。
- SQLite 仅用于本地演示；不是生产 MongoDB 部署。
- 不修改正式发布注册表，不满足正式 Playtest Participant 审批要求。
- 阿里云、VPN、域名、ICP 备案、真实邮件与真实玩家数据均不属于本轮。