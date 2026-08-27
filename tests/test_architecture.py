import ast
from pathlib import Path

SOURCE_ROOT = Path(__file__).parents[1] / "src" / "kotonoha"


def _python_modules():
    return tuple(path for path in SOURCE_ROOT.rglob("*.py") if path.is_file())


def _imports(path: Path) -> tuple[ast.Import | ast.ImportFrom, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return tuple(node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))


def _module_names(path: Path) -> set[str]:
    """Return absolute and relative import spellings used by one module."""
    names: set[str] = set()
    for node in _imports(path):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif node.module is not None:
            names.add("." * node.level + node.module)
    return names


def _module_name(path: Path) -> str:
    """Return the package module name represented by a source path."""
    parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(("kotonoha", *parts))


def _absolute_imports(path: Path) -> set[str]:
    """Resolve AST import nodes enough to enforce package dependency direction."""
    module_parts = _module_name(path).split(".")
    package_parts = module_parts[:-1]
    resolved: set[str] = set()
    for node in _imports(path):
        if isinstance(node, ast.Import):
            resolved.update(alias.name for alias in node.names)
            continue
        if node.level == 0:
            base = [] if node.module is None else node.module.split(".")
        else:
            root_length = len(package_parts) - (node.level - 1)
            if root_length < 0:
                continue
            base = package_parts[:root_length]
            if node.module is not None:
                base.extend(node.module.split("."))
        if node.module is None:
            resolved.update(".".join((*base, alias.name)) for alias in node.names)
        else:
            resolved.add(".".join(base))
    return resolved


#: The composition root is the only module outside the platform package allowed to
#: name the concrete bridge. Overlay defaults are built by the platform factory.
_BRIDGE_NAMERS = {"controller.py"}

#: The concrete native bridge, however it is spelled at the import site.
_BRIDGE_SYMBOLS = {"LayerShellController"}


def test_ui_does_not_reach_the_native_bridge():
    """No UI module may import the native bridge, by module path or by re-export.

    Rejecting `platform.native` alone left the boundary open: `platform/__init__.py`
    re-exports LayerShellController, so `from .platform import LayerShellController`
    hands a UI module the concrete bridge while the old check passed. The sole
    remaining call site is the composition root listed above.
    """
    violations = []
    for path in _python_modules():
        if "platform" in path.relative_to(SOURCE_ROOT).parts:
            continue
        for node in _imports(path):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("platform.native"):
                violations.append(f"{path.name}: platform.native")
            if isinstance(node, ast.Import) and any(
                alias.name == "kotonoha.platform.native" or alias.name.endswith(".platform.native")
                for alias in node.names
            ):
                violations.append(f"{path.name}: platform.native")
            if isinstance(node, ast.Import) and any(alias.name == "ctypes" for alias in node.names):
                violations.append(f"{path.name}: ctypes")
            if isinstance(node, ast.ImportFrom) and node.module == "ctypes":
                violations.append(f"{path.name}: ctypes")
            if (
                isinstance(node, ast.ImportFrom)
                and path.name not in _BRIDGE_NAMERS
                and any(alias.name in _BRIDGE_SYMBOLS for alias in node.names)
            ):
                violations.append(f"{path.name}: {node.names[0].name} through the package re-export")
    assert not violations, (
        "UI modules must depend on the platform contract, not the native bridge: " + ", ".join(violations)
    )


def test_overlay_contracts_is_toolkit_free():
    path = SOURCE_ROOT / "platform" / "overlay_contracts.py"
    assert all(
        not (
            isinstance(node, ast.Import)
            and any(alias.name == "PyQt6" or alias.name.startswith("PyQt6.") for alias in node.names)
            or isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == "PyQt6" or node.module.startswith("PyQt6."))
        )
        for node in _imports(path)
    )


def test_overlay_window_lives_in_the_overlay_package():
    """The overlay window and its collaborators have one package owner."""
    assert (SOURCE_ROOT / "overlay").is_dir()
    assert (SOURCE_ROOT / "overlay" / "__init__.py").is_file()
    assert (SOURCE_ROOT / "overlay" / "window.py").is_file()
    assert not (SOURCE_ROOT / "overlay.py").exists()


def test_desktop_environment_has_one_reader():
    """Only the platform probe names XDG_CURRENT_DESKTOP.

    Read from the parsed module rather than from its text: the previous check
    counted any file whose source contained the string, so a mention in a comment
    or a docstring counted as a reader and a formatting change could have hidden a
    real one. A key assembled at runtime is beyond any static check, and this test
    does not claim to catch that.
    """
    readers = []
    for path in _python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings = {
            node.body[0].value
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        if any(
            isinstance(node, ast.Constant) and node.value == "XDG_CURRENT_DESKTOP" and node not in docstrings
            for node in ast.walk(tree)
        ):
            readers.append(path.relative_to(SOURCE_ROOT).as_posix())
    assert readers == ["platform/detect.py"]


def test_the_title_grammar_knows_nothing_about_matching():
    # The grammar has to serve every ingest path — MPRIS, a browser bridge, a player
    # plugin — so it must not depend on how a candidate is scored. When the two lived
    # in one module a rule could only be reached through the matcher, and the three
    # bilibili rules ended up stranded in the MPRIS parser for exactly that reason.
    titles = SOURCE_ROOT / "lyrics" / "titles.py"

    for node in _imports(titles):
        module = getattr(node, "module", "") or ""
        assert "match" not in module.split("."), f"titles.py imports {module}"
        for alias in node.names:
            assert "match" not in alias.name.split("."), f"titles.py imports {alias.name}"


def test_the_matcher_holds_no_platform_grammar():
    # Every regex that describes how a publisher decorates a title belongs to the
    # grammar module; match.py should only be scoring.
    match_source = (SOURCE_ROOT / "lyrics" / "match.py").read_text(encoding="utf-8")

    assert "re.compile" not in match_source, "a grammar rule has drifted back into the matcher"


def test_lyrics_contract_modules_are_toolkit_and_transport_neutral():
    """Domain/source contracts must not acquire Qt, aiohttp, or display imports."""
    contract_paths = (
        SOURCE_ROOT / "lyrics" / "models.py",
        SOURCE_ROOT / "lyrics" / "ownership.py",
        SOURCE_ROOT / "lyrics" / "sources.py",
        SOURCE_ROOT / "lyrics" / "workflow.py",
        SOURCE_ROOT / "lyrics" / "live_source.py",
        SOURCE_ROOT / "playback" / "models.py",
    )
    forbidden = ("PyQt6", "aiohttp", "display", "QtDisplayPublisher")
    violations = [
        f"{path.name}: {module}"
        for path in contract_paths
        for module in _module_names(path)
        if any(part in module for part in forbidden)
    ]
    assert not violations, "feature contracts must not depend on UI or concrete transports: " + ", ".join(violations)


def test_display_publisher_has_one_application_owner():
    """Provider and receiver adapters may not construct their own Qt publisher."""
    owners: list[str] = []
    for path in _python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "QtDisplayPublisher":
                owners.append(path.relative_to(SOURCE_ROOT).as_posix())
    assert owners == ["display/coordinator.py"]


def test_provider_boundaries_do_not_retain_legacy_display_or_gate_contracts():
    """Player adapters publish through application ports and source ownership."""
    forbidden = {"LyricsState", "LyricsSnapshot", "SourceGate", "QtDisplayPublisher"}
    violations: list[str] = []
    for name in ("mpris.py", "mpris_lyrics.py", "cider_api.py"):
        path = SOURCE_ROOT / "providers" / name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Name) and node.id in forbidden:
                violations.append(f"{name}: {node.id}")
            if isinstance(node, ast.Attribute) and node.attr in forbidden:
                violations.append(f"{name}: {node.attr}")
    assert not violations, "provider boundaries retain legacy contracts: " + ", ".join(violations)


def test_timeline_engine_is_clock_only():
    """Timeline state must not import lyric policy or presentation modules."""
    path = SOURCE_ROOT / "display" / "timeline.py"
    forbidden = ("lyrics", "rules", "presentation", "PyQt6")
    violations = [module for module in _module_names(path) if any(part in module for part in forbidden)]
    assert not violations, "TimelineEngine must own clock state only: " + ", ".join(sorted(violations))


def test_display_engine_is_the_single_policy_owner():
    """The display policy class must have one concrete definition."""
    owners: list[str] = []
    for path in _python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.ClassDef) and node.name == "DisplayEngine" for node in ast.walk(tree)):
            owners.append(path.relative_to(SOURCE_ROOT).as_posix())
    assert owners == ["display/presentation.py"]


def test_overlay_consumes_display_progress_without_owning_display_policy():
    """The Qt renderer may paint progress but may not select or calculate it."""
    path = SOURCE_ROOT / "overlay" / "window.py"
    forbidden_modules = ("display.karaoke", "display.rules", "display.presentation", "lyrics.select")
    imported = _module_names(path)
    assert not any(any(part in module for part in forbidden_modules) for module in imported), imported

    forbidden_names = {
        "active_word_index",
        "find_current_index",
        "in_interlude",
        "interlude_at",
        "interlude_text",
        "line_fill_fraction",
        "line_progress",
        "word_fill_fraction",
        "word_fill_fractions",
    }
    names = {
        node.id
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Name)
    }
    assert not names.intersection(forbidden_names)


def test_playback_application_boundary_does_not_expose_dbus_dynamic_values():
    """D-Bus variants must be normalized before reaching playback coordination."""
    path = SOURCE_ROOT / "providers" / "mpris_playback.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    dynamic_names = [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == "Any"]
    assert not dynamic_names, "playback coordination must use typed property-change values"


def test_playback_domain_does_not_depend_on_player_adapters():
    """Neutral playback models cannot import a concrete provider package."""
    violations = []
    for path in (SOURCE_ROOT / "playback").rglob("*.py"):
        for imported in _absolute_imports(path):
            if imported == "kotonoha.providers" or imported.startswith("kotonoha.providers."):
                violations.append(f"{path.relative_to(SOURCE_ROOT)} -> {imported}")
    assert not violations, "playback domain depends on provider adapters: " + ", ".join(violations)


def test_large_ui_modules_are_explicitly_scoped():
    offenders: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        if lines > 800:
            offenders.append(f"{relative} ({lines} lines)")
    assert not offenders, "split oversized modules by responsibility: " + ", ".join(offenders)


def test_application_code_does_not_swallow_unknown_failures():
    """Broad exception handlers must not become an application control path."""
    violations: list[str] = []
    for path in _python_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}:
                violations.append(path.relative_to(SOURCE_ROOT).as_posix())
    assert not violations, "catch expected boundary failures explicitly: " + ", ".join(violations)
