# PR #27 · 深层 JSON 基线对比原始证据

2026-11-17。此文件保留实际执行输出（仅去除行尾空白）（生成临时目录路径仅为测试产物）。未修改loader或该测试；没有调整递归限制、替换JSON解析器或弱化断言。

目标源码由`git archive origin/codex/bootstrap backend`导出到临时目录，用同一backend/.venv解释器/依赖、`PYTHONPATH=<目标源码>/backend/src`运行原测试；PR分支直接运行相同节点。探针输出的loader路径证明导入了各自代码，SHA256相同：`0e0df909d3dfdb034f51f56fd7a1b2677f40f2d633dbdd122ee6000ee19d469c`。

四次pytest均使用`-vv --tb=long`。3.12.4使用uv校验下载的独立Linux解释器，并显式加载相同依赖与各自源目录。3.12.4与3.12.14均失败；不支持“仅3.12补丁版本导致”的结论。原报告来自Windows，当前没有相同Windows构建，不能断言原平台的精确根因。当前可确认：这是目标分支已存在的、对解析器深度阈值作固定假设的兼容性失败，并非T11.2引入。

## 目标分支 acca4ed · CPython 3.12.14

```text
============================= test session starts ==============================
platform linux -- Python 3.12.14, pytest-9.0.2, pluggy-1.7.0 -- /workspace/two-worlds-agent-game/backend/.venv/bin/python
cachedir: .pytest_cache
rootdir: /tmp/t11-2-review-baseline/backend
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 1 item

../tmp/t11-2-review-baseline/backend/tests/content/test_loader.py::test_json_parser_recursion_failure_is_reported_without_a_raw_traceback FAILED [100%]

=================================== FAILURES ===================================
____ test_json_parser_recursion_failure_is_reported_without_a_raw_traceback ____

library = PosixPath('/tmp/pytest-of-agent/pytest-9/test_json_parser_recursion_fai0/scripts')

    def test_json_parser_recursion_failure_is_reported_without_a_raw_traceback(library):
        (library / "schema_example/1.0.0.json").write_bytes(
            b"[" * 3000 + b"0" + b"]" * 3000
        )
>       expect_error("CONTENT_INVALID_JSON", library)

/tmp/t11-2-review-baseline/backend/tests/content/test_loader.py:171:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

code = 'CONTENT_INVALID_JSON'
root = PosixPath('/tmp/pytest-of-agent/pytest-9/test_json_parser_recursion_fai0/scripts')
script_id = 'schema_example', version = '1.0.0'

    def expect_error(code, root, script_id="schema_example", version="1.0.0"):
        api = loader_api()
        with pytest.raises(api.ScriptLoadError) as error:
            api.ScriptLoader(root).load(script_id, version)
>       assert error.value.code == code
E       AssertionError: assert 'CONTENT_INVALID_SCHEMA' == 'CONTENT_INVALID_JSON'
E
E         - CONTENT_INVALID_JSON
E         ?                 - ^^
E         + CONTENT_INVALID_SCHEMA
E         ?                  ^^^^^

/tmp/t11-2-review-baseline/backend/tests/content/test_loader.py:42: AssertionError
=========================== short test summary info ============================
FAILED ../tmp/t11-2-review-baseline/backend/tests/content/test_loader.py::test_json_parser_recursion_failure_is_reported_without_a_raw_traceback - AssertionError: assert 'CONTENT_INVALID_SCHEMA' == 'CONTENT_INVALID_JSON'

  - CONTENT_INVALID_JSON
  ?                 - ^^
  + CONTENT_INVALID_SCHEMA
  ?                  ^^^^^
============================== 1 failed in 0.26s ===============================
```

## PR 修复前 61f2e19 · 同一 CPython 3.12.14

```text
============================= test session starts ==============================
platform linux -- Python 3.12.14, pytest-9.0.2, pluggy-1.7.0 -- /workspace/two-worlds-agent-game/backend/.venv/bin/python
cachedir: .pytest_cache
rootdir: /workspace/two-worlds-agent-game/backend
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 1 item

backend/tests/content/test_loader.py::test_json_parser_recursion_failure_is_reported_without_a_raw_traceback FAILED [100%]

=================================== FAILURES ===================================
____ test_json_parser_recursion_failure_is_reported_without_a_raw_traceback ____

library = PosixPath('/tmp/pytest-of-agent/pytest-8/test_json_parser_recursion_fai0/scripts')

    def test_json_parser_recursion_failure_is_reported_without_a_raw_traceback(library):
        (library / "schema_example/1.0.0.json").write_bytes(
            b"[" * 3000 + b"0" + b"]" * 3000
        )
>       expect_error("CONTENT_INVALID_JSON", library)

backend/tests/content/test_loader.py:171:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

code = 'CONTENT_INVALID_JSON'
root = PosixPath('/tmp/pytest-of-agent/pytest-8/test_json_parser_recursion_fai0/scripts')
script_id = 'schema_example', version = '1.0.0'

    def expect_error(code, root, script_id="schema_example", version="1.0.0"):
        api = loader_api()
        with pytest.raises(api.ScriptLoadError) as error:
            api.ScriptLoader(root).load(script_id, version)
>       assert error.value.code == code
E       AssertionError: assert 'CONTENT_INVALID_SCHEMA' == 'CONTENT_INVALID_JSON'
E
E         - CONTENT_INVALID_JSON
E         ?                 - ^^
E         + CONTENT_INVALID_SCHEMA
E         ?                  ^^^^^

backend/tests/content/test_loader.py:42: AssertionError
=========================== short test summary info ============================
FAILED backend/tests/content/test_loader.py::test_json_parser_recursion_failure_is_reported_without_a_raw_traceback - AssertionError: assert 'CONTENT_INVALID_SCHEMA' == 'CONTENT_INVALID_JSON'

  - CONTENT_INVALID_JSON
  ?                 - ^^
  + CONTENT_INVALID_SCHEMA
  ?                  ^^^^^
============================== 1 failed in 0.23s ===============================
```

## 目标分支 acca4ed · Linux CPython 3.12.4

```text
============================= test session starts ==============================
platform linux -- Python 3.12.4, pytest-9.0.2, pluggy-1.7.0 -- /workspace/.cache/python/cpython-3.12.4-linux-x86_64-gnu/bin/python3.12
cachedir: .pytest_cache
rootdir: /tmp/t11-2-review-baseline/backend
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 1 item

../tmp/t11-2-review-baseline/backend/tests/content/test_loader.py::test_json_parser_recursion_failure_is_reported_without_a_raw_traceback FAILED [100%]

=================================== FAILURES ===================================
____ test_json_parser_recursion_failure_is_reported_without_a_raw_traceback ____

library = PosixPath('/tmp/pytest-of-agent/pytest-11/test_json_parser_recursion_fai0/scripts')

    def test_json_parser_recursion_failure_is_reported_without_a_raw_traceback(library):
        (library / "schema_example/1.0.0.json").write_bytes(
            b"[" * 3000 + b"0" + b"]" * 3000
        )
>       expect_error("CONTENT_INVALID_JSON", library)

/tmp/t11-2-review-baseline/backend/tests/content/test_loader.py:171:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

code = 'CONTENT_INVALID_JSON'
root = PosixPath('/tmp/pytest-of-agent/pytest-11/test_json_parser_recursion_fai0/scripts')
script_id = 'schema_example', version = '1.0.0'

    def expect_error(code, root, script_id="schema_example", version="1.0.0"):
        api = loader_api()
        with pytest.raises(api.ScriptLoadError) as error:
            api.ScriptLoader(root).load(script_id, version)
>       assert error.value.code == code
E       AssertionError: assert 'CONTENT_INVALID_SCHEMA' == 'CONTENT_INVALID_JSON'
E
E         - CONTENT_INVALID_JSON
E         ?                 - ^^
E         + CONTENT_INVALID_SCHEMA
E         ?                  ^^^^^

/tmp/t11-2-review-baseline/backend/tests/content/test_loader.py:42: AssertionError
=========================== short test summary info ============================
FAILED ../tmp/t11-2-review-baseline/backend/tests/content/test_loader.py::test_json_parser_recursion_failure_is_reported_without_a_raw_traceback - AssertionError: assert 'CONTENT_INVALID_SCHEMA' == 'CONTENT_INVALID_JSON'

  - CONTENT_INVALID_JSON
  ?                 - ^^
  + CONTENT_INVALID_SCHEMA
  ?                  ^^^^^
============================== 1 failed in 0.23s ===============================
```

## PR 分支 · Linux CPython 3.12.4

```text
============================= test session starts ==============================
platform linux -- Python 3.12.4, pytest-9.0.2, pluggy-1.7.0 -- /workspace/.cache/python/cpython-3.12.4-linux-x86_64-gnu/bin/python3.12
cachedir: .pytest_cache
rootdir: /workspace/two-worlds-agent-game/backend
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 1 item

backend/tests/content/test_loader.py::test_json_parser_recursion_failure_is_reported_without_a_raw_traceback FAILED [100%]

=================================== FAILURES ===================================
____ test_json_parser_recursion_failure_is_reported_without_a_raw_traceback ____

library = PosixPath('/tmp/pytest-of-agent/pytest-14/test_json_parser_recursion_fai0/scripts')

    def test_json_parser_recursion_failure_is_reported_without_a_raw_traceback(library):
        (library / "schema_example/1.0.0.json").write_bytes(
            b"[" * 3000 + b"0" + b"]" * 3000
        )
>       expect_error("CONTENT_INVALID_JSON", library)

backend/tests/content/test_loader.py:171:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

code = 'CONTENT_INVALID_JSON'
root = PosixPath('/tmp/pytest-of-agent/pytest-14/test_json_parser_recursion_fai0/scripts')
script_id = 'schema_example', version = '1.0.0'

    def expect_error(code, root, script_id="schema_example", version="1.0.0"):
        api = loader_api()
        with pytest.raises(api.ScriptLoadError) as error:
            api.ScriptLoader(root).load(script_id, version)
>       assert error.value.code == code
E       AssertionError: assert 'CONTENT_INVALID_SCHEMA' == 'CONTENT_INVALID_JSON'
E
E         - CONTENT_INVALID_JSON
E         ?                 - ^^
E         + CONTENT_INVALID_SCHEMA
E         ?                  ^^^^^

backend/tests/content/test_loader.py:42: AssertionError
=========================== short test summary info ============================
FAILED backend/tests/content/test_loader.py::test_json_parser_recursion_failure_is_reported_without_a_raw_traceback - AssertionError: assert 'CONTENT_INVALID_SCHEMA' == 'CONTENT_INVALID_JSON'

  - CONTENT_INVALID_JSON
  ?                 - ^^
  + CONTENT_INVALID_SCHEMA
  ?                  ^^^^^
============================== 1 failed in 0.27s ===============================
```

## 实际异常链与触发深度

以下探针没有打印深层数组正文。

```text
Python: 3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]
Source: /workspace/two-worlds-agent-game/backend/src/twoworlds/content/loader.py
Loader SHA256: 0e0df909d3dfdb034f51f56fd7a1b2677f40f2d633dbdd122ee6000ee19d469c
recursionlimit: 1000 scanner: <class '_json.Scanner'>
depth 500 JSON result: list
depth 1500 JSON result: list
depth 3000 JSON result: list
loader exception: ScriptLoadError CONTENT_INVALID_SCHEMA
Traceback (most recent call last):
  File "/workspace/two-worlds-agent-game/work/t11-2-review/json_probe.py", line 19, in <module>
    try: loader.ScriptLoader(root).load('schema_example','1.0.0')
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/workspace/two-worlds-agent-game/backend/src/twoworlds/content/loader.py", line 107, in load
    raise ScriptLoadError("CONTENT_INVALID_SCHEMA") from None
twoworlds.content.loader.ScriptLoadError: 剧本未通过内容结构或引用校验。

suppressed internal exception: ValidationError
  File "/workspace/two-worlds-agent-game/backend/src/twoworlds/content/loader.py", line 104, in load
    script = ScriptVersion.model_validate(data)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/workspace/two-worlds-agent-game/backend/.venv/lib/python3.12/site-packages/pydantic/main.py", line 790, in model_validate
    return cls.__pydantic_validator__.validate_python(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

validation errors without input: [{'type': 'model_type', 'loc': (), 'msg': 'Input should be a valid dictionary or instance of ScriptVersion', 'ctx': {'class_name': 'ScriptVersion'}, 'url': 'https://errors.pydantic.dev/2.14/v/model_type'}]
depth 10000 JSON exception: RecursionError
```

目标探针使用相同解释器并确认独立源码位置：

```text
Python: 3.12.14 (main, Aug 25 2026, 14:00:49) [Clang 22.1.3 ]
Source: /tmp/t11-2-review-baseline/backend/src/twoworlds/content/loader.py
Loader SHA256: 0e0df909d3dfdb034f51f56fd7a1b2677f40f2d633dbdd122ee6000ee19d469c
recursionlimit: 1000 scanner: <class '_json.Scanner'>
depth 500 JSON result: list
depth 1500 JSON result: list
depth 3000 JSON result: list
loader exception: ScriptLoadError CONTENT_INVALID_SCHEMA
Traceback (most recent call last):
  File "/workspace/two-worlds-agent-game/work/t11-2-review/json_probe.py", line 19, in <module>
    try: loader.ScriptLoader(root).load('schema_example','1.0.0')
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/tmp/t11-2-review-baseline/backend/src/twoworlds/content/loader.py", line 107, in load
    raise ScriptLoadError("CONTENT_INVALID_SCHEMA") from None
twoworlds.content.loader.ScriptLoadError: 剧本未通过内容结构或引用校验。

suppressed internal exception: ValidationError
  File "/tmp/t11-2-review-baseline/backend/src/twoworlds/content/loader.py", line 104, in load
    script = ScriptVersion.model_validate(data)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/workspace/two-worlds-agent-game/backend/.venv/lib/python3.12/site-packages/pydantic/main.py", line 790, in model_validate
    return cls.__pydantic_validator__.validate_python(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

validation errors without input: [{'type': 'model_type', 'loc': (), 'msg': 'Input should be a valid dictionary or instance of ScriptVersion', 'ctx': {'class_name': 'ScriptVersion'}, 'url': 'https://errors.pydantic.dev/2.14/v/model_type'}]
depth 10000 JSON exception: RecursionError
```

额外Linux3.12.4探针：

```text
Python: 3.12.4 (main, Jul 25 2024, 22:42:01) [Clang 18.1.8 ]
Source: /workspace/two-worlds-agent-game/backend/src/twoworlds/content/loader.py
Loader SHA256: 0e0df909d3dfdb034f51f56fd7a1b2677f40f2d633dbdd122ee6000ee19d469c
recursionlimit: 1000 scanner: <class '_json.Scanner'>
depth 500 JSON result: list
depth 1500 JSON result: list
depth 3000 JSON result: list
loader exception: ScriptLoadError CONTENT_INVALID_SCHEMA
Traceback (most recent call last):
  File "/workspace/two-worlds-agent-game/work/t11-2-review/json_probe.py", line 19, in <module>
    try: loader.ScriptLoader(root).load('schema_example','1.0.0')
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/workspace/two-worlds-agent-game/backend/src/twoworlds/content/loader.py", line 107, in load
    raise ScriptLoadError("CONTENT_INVALID_SCHEMA") from None
twoworlds.content.loader.ScriptLoadError: 剧本未通过内容结构或引用校验。

suppressed internal exception: ValidationError
  File "/workspace/two-worlds-agent-game/backend/src/twoworlds/content/loader.py", line 104, in load
    script = ScriptVersion.model_validate(data)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/workspace/two-worlds-agent-game/backend/.venv/lib/python3.12/site-packages/pydantic/main.py", line 790, in model_validate
    return cls.__pydantic_validator__.validate_python(
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

validation errors without input: [{'type': 'model_type', 'loc': (), 'msg': 'Input should be a valid dictionary or instance of ScriptVersion', 'ctx': {'class_name': 'ScriptVersion'}, 'url': 'https://errors.pydantic.dev/2.14/v/model_type'}]
depth 10000 JSON exception: RecursionError
```
