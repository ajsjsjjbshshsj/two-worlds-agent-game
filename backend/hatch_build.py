"""构建时复用发布校验，只收集明确的草稿JSON和已登记快照文件。"""

import importlib
import importlib.util
import hashlib
from pathlib import Path
import sys

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        content = root / "src/twoworlds/content"
        # 隔离构建尚未安装本项目；用独立包名加载源码，避免修改sys.path或借用开发安装。
        name = (
            "_twoworlds_build_content_"
            + hashlib.sha256(str(content).encode()).hexdigest()[:16]
        )
        spec = importlib.util.spec_from_file_location(
            name, content / "__init__.py", submodule_search_locations=[str(content)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        publication = importlib.import_module(f"{name}.publication")
        loader = importlib.import_module(f"{name}.loader")
        selected = [publication.safe_path(content, "published/registry.json")]
        scripts = content / "scripts"
        for path in sorted(scripts.glob("*/*.json")):
            identifier, number = publication._reference(path.parent.name, path.stem)
            loader.ScriptLoader(scripts).load(identifier, number)
            selected.append(
                publication.safe_path(scripts, f"{identifier}/{number}.json")
            )
        store = publication.PublicationStore(content / "published")
        for metadata in store.catalog():
            base = content / "published" / metadata.id / metadata.content_version
            script = store.load(metadata.id, metadata.content_version)
            for relative in [
                "release.json",
                f"scripts/{metadata.id}/{metadata.content_version}.json",
                *[f"assets/{asset.path}" for asset in script.media],
            ]:
                selected.append(publication.safe_path(base, relative))
        # force_include只针对上面验证过的明确文件；未登记资源、隐藏暂存和杂项不入包。
        for path in selected:
            relative = path.relative_to(root / "src")
            target = relative if self.target_name == "wheel" else Path("src") / relative
            build_data["force_include"][str(path)] = target.as_posix()
