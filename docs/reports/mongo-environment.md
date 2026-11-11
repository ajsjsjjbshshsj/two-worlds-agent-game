# T05.1 · MongoDB 环境、驱动与真实连接验证

日期：2026-11-11。本轮仅准备本地数据库与驱动，T05 整体尚未完成；不实现 MongoRepository、业务索引、API、身份、WS、前端或 T06。

## 起点与工作区

PR #12 已合并：`2026-11-11T10:54:41Z`，合并提交 `52fa1d6f135f5ddac311433f08d8dc49dd8978e6`。fetch 后确认它就是最新远端 `codex/bootstrap`，从该提交建立 `codex/t05-1-mongo-environment`。

交付位于 `F:\two-worlds-agent-game\work\pr-t01-1-schema`。开始时该工作树干净；主目录 `F:\two-worlds-agent-game` 有旧本地提交及用户未提交学习文件，未覆盖、未推送这些内容。主目录的旧交接与代码状态不作为本轮基线。

初查 Docker Desktop 未运行，Linux 引擎管道不存在；27017 无监听，Windows 未发现 Mongo 服务。项目 Python 3.12 虚拟环境没有 PyMongo。启动已有 Docker Desktop 后，检查所有容器：无 `twoworlds-mongo`、无 `twoworlds-mongo-data` 卷，也无本地 `mongo:8.0` 镜像。参考项目的 Atlas Local 容器保持停止状态，未复用其数据。Docker 自身重启策略使部分原有其他项目容器自动启动，本轮没有逐个启动、停止、重启或修改它们。

## 实际版本与目标

| 项目 | 实际记录 |
| --- | --- |
| Docker Desktop | 4.70.0 (224270)，desktop-linux |
| Docker 客户端 / Engine | 29.4.0 / 29.4.0，API 1.54，Linux amd64 |
| Python | 3.12.4，项目工作树 backend/.venv |
| uv | 0.11.2 |
| PyMongo | 4.19.0，同步 MongoClient；包元数据要求 Python >=3.11 |
| dnspython | 2.9.2，PyMongo 的新增传递依赖 |
| MongoDB 服务端 | 8.0.34，经同步客户端 server_info 验证 |
| 实际镜像 | mongodb/mongodb-atlas-local:8.0，直接以 mongod 为入口，不运行 Atlas 附加组件 |
| 镜像摘要 | sha256:cd79e87b95ca4184668aacd35ca74493930727ead8d1789e37461ffbe8ef12a6 |
| 专用容器 / 数据卷 | twoworlds-mongo / twoworlds-mongo-data（/data/db） |
| 端口 / 重启策略 | 仅 127.0.0.1:27017 / unless-stopped |
| 连接地址（无凭证） | mongodb://127.0.0.1:27017/?directConnection=true |

URI 仅通过进程环境变量 `MONGO_URI` 读取，不将真实凭证、完整环境或客户端配置输出到源码/日志/Git。此处是无凭证的本地回环地址；未来若换成认证 URI，报告应只写 `mongodb://<redacted>@<host>:<port>/`。

## 依赖变更

执行 `uv add --project backend --bounds exact pymongo --python .\backend\.venv\Scripts\python.exe --no-python-downloads --cache-dir F:/two-worlds-agent-game/work/uv-cache`。

pyproject 增加 `pymongo==4.19.0`，uv.lock 由 uv 更新。比较旧/新 TOML 中每个锁定包名和版本，原有 22 包全部保留原版本，只新增 pymongo、dnspython，总计 24 包。uv 重建并安装本项目的 editable 包；没有修改全局 Python 环境，没有使用 `--upgrade` 或手工编辑锁文件。

[PyMongo 官方入门文档](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/get-started/) 提供同步 MongoClient 的连接方式。本轮直接使用同步客户端做环境验证，不新增仓储或应用服务。

## 数据库验证

`mongo:8.0` 拉取从 19:07 左右开始，约十分钟后仍有层未完成；没有宣称它拉取成功。后续用带终端进度的拉取检查也未完成，最终结束了这两次本轮下载。没有改 Docker 全局镜像源或复用参考项目容器。

为完成真实验证，采用已缓存的 MongoDB 官方 `mongodb/mongodb-atlas-local:8.0` 镜像；先用 `--rm --network none --entrypoint mongod ... --version` 在无卷临时容器中确认版本 8.0.34。然后创建独立命名卷，初始化空卷的 mongod 用户目录权限，再以 `--entrypoint mongod --bind_ip_all --dbpath /data/db` 启动专用容器。容器内部允许连接，但宿主发布端口仅为 127.0.0.1，不开放公网。实际镜像与建议的 `mongo:8.0` 不同，此差异保留在报告中；没有把缓存镜像改名冒充已拉取的镜像。

缓存镜像继承的健康检查针对 Atlas runner，不适用于只运行 mongod。本轮核验新容器 ID 和任务标签后，仅停止并重建这个新容器，命名数据卷保留，匿名 configdb 卷随旧容器清理。最终健康检查替换为真实 `mongosh` Ping，10 秒间隔、5 秒超时、10 秒启动期、3 次失败阈值。没有修改其他已有容器或卷。缓存镜像还会挂载一个匿名 `/data/configdb` 卷，单机 mongod 不使用它存业务数据。

| 验证 | 实际结果 |
| --- | --- |
| 同步客户端连接、admin Ping | 通过 |
| 显式创建随机临时数据库/集合 | 通过，非正式业务库 |
| 插入中文测试文档、读取比对 | 通过，w=1、journal 确认 |
| 更新 revision=2 并再次读取 | 通过 |
| 保留数据卷重建专用容器后读取 | 通过 |
| 显式 docker restart 后重新连接与读取 | 通过，文档内容及 revision 不变 |
| 删除测试文档，再查询为空 | 通过，deleted_count=1 |
| 删除随机临时数据库并确认不存在 | 通过 |
| 最终容器健康状态及清理复核 | healthy，连续 Ping 检查退出码 0，临时库已不存在 |

临时库为 `twoworlds_env_t051_e1024b865e9d4016b05487125ab980a1`。准备阶段于 UTC 11:18:29 完成；重启后的读取、删除和清理于 UTC 11:19:53 完成。最终容器 StartedAt 从 `11:19:29.455676564Z` 变为 `11:19:52.744459956Z`，证明执行了真实重启。测试文档完全为本轮生成的中文样本，没有读取用户剧情或身份数据。

探针用随机 UUID 命名数据库和文档，并在本地忽略的 work 清单中记录归属；删除前核对命名前缀、UUID 和文档内容，只删除该临时库。运行结果仅输出版本、合成库名和布尔值，不打印 URI、环境或凭证。验证均针对真实数据库，没有 mock。临时脚本/清单/JUnit 不进入 PR。

## 已有回归

安装驱动后执行全部 backend 测试：578 项，540 通过、38 失败，0 errors、0 skipped，1 条已有 anyio 弃用警告。其中领域 308、内容 191、仓储 41 项通过。Ruff check 通过，format --check 的 48 文件均正确。离线 `uv lock --check` 通过，24 包一致。全量退出码仍为 1，不将历史 API 缺实现称为全部通过。

逐项比较 PR #12 的 `work/pair-entry-all.xml` 与本轮 `work/t051-all.xml`：38 项失败 ID 和消息完全一致，均为缺 `twoworlds.api.app`；新增/消失失败均为 0。未修改旧测试或加入 skip/xfail。

实际命令：

```powershell
docker version --format '{{json .}}'
docker context show
docker ps -a --format '{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}'
docker volume ls --filter name=twoworlds-mongo-data --format '{{.Name}}'
docker image ls mongo --format '{{.Repository}}:{{.Tag}} | {{.ID}}'
Get-NetTCPConnection -LocalPort 27017 -State Listen -ErrorAction SilentlyContinue
Get-Service '*mongo*' -ErrorAction SilentlyContinue
docker desktop start --detach --timeout 45
docker pull mongo:8.0
uv add --project backend --bounds exact pymongo --python .\backend\.venv\Scripts\python.exe --no-python-downloads --cache-dir F:/two-worlds-agent-game/work/uv-cache
uv lock --project backend --check --offline --cache-dir F:/two-worlds-agent-game/work/uv-cache
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q --tb=short -p no:cacheprovider --basetemp=work/pytest-t051-all --junitxml=work/t051-all.xml
.\backend\.venv\Scripts\python.exe -m ruff check backend/src backend/tests backend/hatch_build.py
.\backend\.venv\Scripts\python.exe -m ruff format --check backend/src backend/tests backend/hatch_build.py
```

最终专用容器配置的等效创建命令如下（只在名称和端口均空闲、卷为本轮新建时使用；已有资源先检查）：

```powershell
docker run --rm --network none --entrypoint mongod mongodb/mongodb-atlas-local:8.0 --version
docker volume create --label com.twoworlds.task=T05.1 twoworlds-mongo-data
docker run --rm --pull never --network none --user 0 --entrypoint sh --mount type=volume,source=twoworlds-mongo-data,target=/data/db mongodb/mongodb-atlas-local:8.0 -c 'chown mongod:mongod /data/db'
docker run -d --pull never --name twoworlds-mongo --label com.twoworlds.task=T05.1 --restart unless-stopped --publish 127.0.0.1:27017:27017 --mount type=volume,source=twoworlds-mongo-data,target=/data/db --health-cmd 'mongosh --quiet --eval "quit(db.adminCommand({ping:1}).ok === 1 ? 0 : 1)"' --health-interval 10s --health-timeout 5s --health-start-period 10s --health-retries 3 --entrypoint mongod mongodb/mongodb-atlas-local:8.0 --bind_ip_all --dbpath /data/db
$env:MONGO_URI = 'mongodb://127.0.0.1:27017/?directConnection=true'
.\backend\.venv\Scripts\python.exe -X utf8 work/t051-mongo-probe.py prepare
docker inspect twoworlds-mongo --format '{{.State.StartedAt}}'
docker restart --timeout 20 twoworlds-mongo
.\backend\.venv\Scripts\python.exe -X utf8 work/t051-mongo-probe.py finish
docker inspect twoworlds-mongo --format '{{json .State}}'
docker inspect twoworlds-mongo --format '{{json .HostConfig.PortBindings}}'
docker inspect twoworlds-mongo --format '{{json .HostConfig.RestartPolicy}}'
docker inspect twoworlds-mongo --format '{{json .Mounts}}'
```

最初容器的 Atlas 健康检查修正时执行了 `docker stop --time 20 twoworlds-mongo` 和 `docker rm -v twoworlds-mongo`，此前核对其本轮创建的完整 ID 与 `com.twoworlds.task=T05.1` 标签。命名卷不随匿名卷清理删除，并在重建后实际读取了原测试文档。Docker 对 stop 的 `--time` 给出弃用提示，命令成功；后续 restart 已使用 `--timeout`。

## 失败与未验证项

- 初查引擎未运行：已通过启动 Docker Desktop 解决。
- 推荐 `mongo:8.0` 下载未完成：已结束本轮拉取，改用已缓存的官方 8.0.34 镜像验证；没有验证推荐镜像本身。
- 缓存镜像的 Atlas 健康检查不适用：已改为 mongosh Ping，不保留错误的健康检查结论。
- 38 项既有 API 契约仍失败，业务入口尚未实现；没有本轮新增后端失败。
- 未验证 MongoRepository、业务索引、并发 CAS、身份/成员安全、生产认证/TLS、复制集、备份或应用服务重启。T05 未完成。

## 环境边界与下一步

此为本机单节点开发环境，仅回环端口，没有生产认证/TLS、复制集、高可用、备份恢复演练或生产运维配置。不能由环境 CRUD 推断 MongoRepository、业务唯一索引、CAS、B 位竞争或共享仓储契约已经完成。SQLite 仍只是显式演示适配器，不添加 Mongo 不可用时自动降级。

下一环节建议 T05.2 实现 MongoRepository 与必要业务索引，复用已有共享仓储契约，并用独立 Mongo 客户端验证 CAS/房间竞争；需用户另行授权。本轮不创建 `storage/mongo.py`、`storage/indexes.py`。完成 T05.1 后停止等待审查。


## 临时探针代码与复现

下面是本轮实际执行的探针。可保存到当前工作树的 `work/t051-mongo-probe.py`，先设置进程环境变量，再按上面的 prepare → 专用容器 restart → finish 顺序运行。work 是忽略目录，脚本与合成测试清单不上传 Git。prepare 拒绝覆盖已有清单；再次验证时另取临时清单路径，不要删除归属不明的测试数据。

```python
"""Temporary T05.1 probe; URI is read only from the process environment."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

import pymongo
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from pymongo.write_concern import WriteConcern

manifest_path = Path("work/t051-mongo-manifest.json")
phase = sys.argv[1]
assert phase in {"prepare", "finish"}
client = MongoClient(
    os.environ["MONGO_URI"],
    serverSelectionTimeoutMS=2000,
    connectTimeoutMS=2000,
    socketTimeoutMS=3000,
)
try:
    for attempt in range(15):
        try:
            assert client.admin.command("ping")["ok"] == 1
            break
        except ConnectionFailure:
            if attempt == 14:
                raise RuntimeError("MongoDB did not become ready") from None
            time.sleep(1)
    if phase == "prepare":
        assert not manifest_path.exists(), "Probe manifest already exists"
        marker = uuid4().hex
        name = "twoworlds_env_t051_" + marker
        assert name not in client.list_database_names()
        manifest_path.write_text(
            json.dumps({"database": name, "marker": marker}), encoding="utf-8"
        )
        database = client[name]
        collection = database.create_collection(
            "probe", write_concern=WriteConcern(w=1, j=True)
        )
        document = {"_id": marker, "task": "T05.1", "text": "跨时灯塔连接验证", "revision": 1}
        assert collection.insert_one(document).acknowledged
        assert collection.find_one({"_id": marker}) == document
        updated = collection.update_one({"_id": marker}, {"$set": {"revision": 2}})
        assert updated.matched_count == updated.modified_count == 1
        assert collection.find_one({"_id": marker}) == document | {"revision": 2}
        result = {
            "phase": phase,
            "at_utc": datetime.now(timezone.utc).isoformat(),
            "python": sys.version.split()[0],
            "pymongo": pymongo.version,
            "mongodb": client.server_info()["version"],
            "database": name,
            "ping": True,
            "insert": True,
            "read": True,
            "update": True,
            "journal_acknowledged": True,
        }
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        name, marker = manifest["database"], manifest["marker"]
        assert re.fullmatch(r"[0-9a-f]{32}", marker)
        assert name == "twoworlds_env_t051_" + marker
        document = client[name].probe.find_one({"_id": marker})
        assert document == {
            "_id": marker, "task": "T05.1", "text": "跨时灯塔连接验证", "revision": 2
        }
        assert client[name].probe.delete_one({"_id": marker}).deleted_count == 1
        assert client[name].probe.find_one({"_id": marker}) is None
        client.drop_database(name)
        assert name not in client.list_database_names()
        result = {
            "phase": phase,
            "at_utc": datetime.now(timezone.utc).isoformat(),
            "database": name,
            "ping_after_restart": True,
            "persisted_after_restart": True,
            "delete": True,
            "temporary_database_removed": True,
        }
    Path(f"work/t051-mongo-{phase}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
finally:
    client.close()
```
