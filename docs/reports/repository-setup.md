# T00.2.1 · 本地 Git 与 GitHub 仓库设置

日期：2026-10-26，Asia/Shanghai。

## 1. 本环节范围与状态

用户明确要求“创建git仓库，并创建github仓库”。本环节建立独立本地Git、忽略规则、本地基线提交、GitHub空私有仓库和origin；不进入工程目录与业务实现。

| 项目 | 结果 |
| --- | --- |
| 本地仓库 | F:\two-worlds-agent-game\.git |
| Git根目录 | F:/two-worlds-agent-game，不再向上使用F:/父仓库 |
| 当前分支 | codex/bootstrap |
| GitHub | [ajsjsjjbshshsj/two-worlds-agent-game](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game) |
| 可见性 | PRIVATE，已通过GitHub CLI查询确认 |
| origin | https://github.com/ajsjsjjbshshsj/two-worlds-agent-game.git |
| 远端内容 | 创建后查询isEmpty=true；尚未上传项目文件 |
| 推送 | 自动审批拒绝，等待用户明确授权上传当前文件范围到上述远端 |

本地基线提交在本环节收尾创建并用git log与git status核验，准确提交标识以实际Git历史和本轮最终回复为准。GitHub创建成功不代表文件已经同步。

## 2. 文件范围

首批基线只包含：`.gitignore`、`.gitattributes`、`AGENTS.md`、`README.md`、`docs/`内设计/报告/架构图、`outputs/`内历史设计和测试配置草稿，以及`work/generate_architecture.py`。

`.gitignore`排除原始聊天HTML/JSON/Markdown及临时work文件，保留架构图生成脚本；同时排除环境密钥、Python缓存、虚拟环境、node_modules、构建产物、本地数据库与日志。原始聊天仅保留本机，README已标明对应本地链接不会在远端可用。

已对暂存文件名检查，并扫描常见GitHub/OpenAI/AWS凭证格式和私钥头，没有匹配。这个有限扫描不是所有敏感信息的绝对保证，因此远端默认私有。

`.gitattributes`让Markdown、Python、配置和SVG以LF保存，PNG按二进制处理；当前SVG工作副本的CRLF规范化提示不表示文件损坏。

## 3. 自动审批记录与待确认动作

最初拟执行的“本地提交 + 创建仓库 + 推送基线”组合命令被自动审批拒绝，整个组合命令没有执行。给出的原因是：用户已授权创建Git仓库，但还未明确授权将这批非公开项目文档导出到这个具体GitHub目的地。

随后执行了更小范围的已授权操作：创建空私有仓库、配置本地origin；没有换方法绕过推送限制。下一步只有在用户明确同意“将本地基线文件上传到该私有仓库”后才推送。

待授权的具体动作：把当前`codex/bootstrap`分支中的上述文件范围推送到`ajsjsjjbshshsj/two-worlds-agent-game`。不包含被忽略的原始聊天、环境文件、缓存和本地数据库。

## 4. 学习顺序

1. 看根目录`.gitignore`：它控制哪些本机文件不进入版本记录；已被跟踪文件不会仅因后来加忽略就自动移除。
2. 看`.gitattributes`：它控制文本换行等跨平台属性，不负责决定文件是否提交。
3. 本地运行`git status`、`git log --oneline -3`、`git remote -v`，观察工作区、提交和远端地址的区别。
4. 打开GitHub私有仓库；它当前是空仓库，因为创建与推送是两件事。

`git add`准备本地快照，`git commit`保存本地历史，`git push`才把提交发送到远端。这也是为什么可以先完成本地版本管理，而把上传保留为明确的最后一步。

## 5. 后续边界

本次没有修改F盘父仓库或参考仓库，没有创建backend/frontend，没有安装依赖、启动数据库或执行产品测试。用户确认上传后完成推送核验，再停在同一学习检查点；T00.2.2工程目录仍需要用户要求继续后执行。
