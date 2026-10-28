# T01.1收尾 · GitHub文件筛选与PR交付

日期：2026-10-28。用户要求排除不必要上传的文件，其余推送GitHub，并从现在起每次改动提交Merge Request，由用户审查合并。GitHub使用Pull Request（PR）。本轮不推进T01.2。

## 文件取舍

- 排除`.idea/`的7个编辑器文件，包括本机解释器名称、模块与检查设置；原本地文件保留。根忽略规则增加`/.idea/`与`*.iml`。
- 保留源码、测试/测试专用JSON、pyproject与uv.lock、中文学习注释、项目设计/验证/交接文档。锁文件与测试样例是复现本阶段行为所需内容，不当作缓存排除。
- 缓存、环境、dist、临时JUnit/验证文件和原始聊天继续按既有规则仅在本机；未上传真实凭证、模型私聊或新素材。

两个未发布提交中混入了IDE文件，因此从GitHub已存在的`7f7b3ba`建立`codex/t01-1-schema-review`，只迁入筛选后的18个项目文件，再加入忽略规则、PR约定、模板和本报告。没有把原`e85eee1`/`6605314`作为PR祖先，避免排除项仍藏在上传历史里。原本地分支与IDE目录不删除、不改写、不强推。

## 固定流程

新约定见[AGENTS第7节](../../AGENTS.md)；GitHub默认目标分支实测为`codex/bootstrap`。每个授权环节完成后，在主题分支提交、推送、创建或更新PR，给用户阅读/验证入口并停止。禁止直接推送目标分支、自动合并或启用自动合并。PR模板位于`.github/PULL_REQUEST_TEMPLATE.md`。

审查中修正了原注释的错误含义：恢复得到新Identity，旧会话是否有效仍取决于期限/撤销/会话窗口；确认信号需灯开启，发车才需引擎开且声呐关；旧版本的成功重试先查幂等回执。测试逻辑保持不变。

## 验证

- PR工作树按uv.lock离线安装22包；隔离导入路径指向该工作树，不依赖原目录的editable源码。
- `python -m pytest backend/tests/content -q`：74 passed。
- 全量测试：74 passed、38 failed，JUnit为112项、0 errors、0 skipped；38项全部缺api.app/storage.sqlite，未进入HTTP行为断言。既有Starlette/AnyIO弃用提示保留。
- Ruff检查通过、19个Python文件格式正确、锁一致性与diff空白检查通过；3个契约文件去掉注释/文档字符串的AST与基线一致。暂存清单22项无排除文件或常见凭证模式；新增历史查询.idea为空。

## 当前交付状态

已推送`codex/t01-1-schema-review`并创建[PR #1](https://github.com/ajsjsjjbshshsj/two-worlds-agent-game/pull/1)，目标`codex/bootstrap`。仅用户审查后合并；本次未合并、不启用自动合并，不执行T01.2。

主学习目录的AGENTS、忽略规则、PR模板和交接/本报告同步为同一份待审查内容，确保跨聊天立即读到新约定；原分支与IDE文件保留，未替换其业务代码。原目录仍含旧本地分支历史，后续不得直接把该分支整串推上默认分支，应先读交接并核对PR与远端状态。
