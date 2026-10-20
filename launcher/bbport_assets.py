import json
import os
import shutil
import subprocess
from pathlib import Path
from bbport_i18n import tr


PORT_DIR = Path(__file__).resolve().parents[1]

FSR4_COMMIT = "ae8d628fae208813172446d1e49ed94150b04658"
FSR4_BASE = f"https://raw.githubusercontent.com/FireBurn/Q2RTX/{FSR4_COMMIT}/baseq2/fsr4_shaders"


def fsr4_files() -> list[str]:
    """The FSR 4 v07 asset set of tools/fetch_fsr4_assets.sh (1080 and 2160 tiers)."""
    files = ["LICENSE-FSR4-v07.txt", "rcas.spv", "spd_auto_exposure.spv"]
    for model in ("native", "quality", "balanced", "performance", "ultraperf", "drs"):
        files += [
            f"fsr4_model_v07_i8_{model}_initializers.bin",
            f"fsr4_model_v07_i8_{model}_pre_weights.bin",
            f"fsr4_model_v07_i8_{model}_shader_manifest.json",
        ]
        for tier in ("1080", "2160"):
            files += [
                f"fsr4_model_v07_i8_{model}_{tier}_pre.spv",
                f"fsr4_model_v07_i8_{model}_{tier}_post.spv",
            ]
            files += [f"fsr4_model_v07_i8_{model}_{tier}_pass{n}.spv" for n in range(1, 13)]
    return files


def validate_fsr4_file(path: Path) -> bool:
    """Validates an FSR 4 asset file for existence, non-emptiness, and format integrity."""
    if not path.is_file():
        return False
    try:
        size = path.stat().st_size
        if size == 0:
            return False
        name = path.name
        if name.endswith(".spv"):
            if size < 20 or size % 4 != 0:
                return False
            with path.open("rb") as f:
                magic = f.read(4)
                if magic not in (b"\x03\x02\x23\x07", b"\x07\x23\x02\x03"):
                    return False
            return True
        if name.endswith("_initializers.bin"):
            return size == 89216
        if name.endswith("_pre_weights.bin"):
            return size == 1024
        if name.endswith("_shader_manifest.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            return isinstance(data, dict) and bool(data)
        if name == "LICENSE-FSR4-v07.txt":
            content = path.read_text(encoding="utf-8", errors="ignore")
            return any(k in content for k in ("FidelityFX", "AMD", "MIT"))
        return True
    except (OSError, ValueError):
        return False


def fsr4_missing(folder: Path | None = None) -> list[str]:
    """Returns missing or invalid FSR 4 assets."""
    dest = folder or (PORT_DIR / "fsr4_shaders")
    return [name for name in fsr4_files() if not validate_fsr4_file(dest / name)]


def fsr4_gpu_supported(port_dir: Path | None = None) -> bool | None:
    """Checks whether the active Vulkan GPU supports FSR 4 INT8 features."""
    root = port_dir or PORT_DIR
    exe = root / "bin" / "bb-gpu-capabilities"
    if not exe.is_file():
        exe = root / "out" / "bb-gpu-capabilities"
    if not exe.is_file():
        return None
    try:
        res = subprocess.run([str(exe), "--fsr4"], capture_output=True, text=True, timeout=10)
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        if lines and lines[-1] == "1":
            return True
        if lines and lines[-1] == "0":
            return False
        return res.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def fsr411_problem(directory: Path, output: str, preset: int) -> str | None:
    w, h = map(int, output.split("x"))
    model = ("t2160" if w > 1920 or h > 1080 else "t1080") + ("_m1" if preset == 4 else "_m0")
    passes = ["spd", "prepass", "pass0_post"]
    for i in range(1, 13):
        passes.extend([f"pass{i}", f"pass{i}_post"])
    passes.extend(["postpass", "rcas"])
    for name in passes:
        path = directory / model / (name + ".spv")
        if not path.is_file() or path.stat().st_size < 20 or path.stat().st_size % 4:
            return tr("Нет или повреждён файл {}").format(f"{model}/{name}.spv")
    path = directory / model / "initializer.bin"
    if not path.is_file() or path.stat().st_size != 131072:
        return tr("Нет или повреждён файл {}").format(f"{model}/initializer.bin")
    return None


KEYBOARD_PROMPTS = "Keyboard Prompts (PCBButtons)"
KEYBOARD_PROMPT_LAYOUT = {
    'key_interact': 'E', 'key_roll': 'Left Shift', 'key_blood_vial': 'R', 'key_use_item': 'Q',
    'key_transform': 'F', 'key_attack': 'Mouse1', 'key_firearm': 'Mouse2',
    'key_strong_attack': 'none', 'key_strong_modifier': 'Left Ctrl', 'key_l3': 'Space',
    'key_lock_on': 'Mouse3', 'key_gestures': 'G', 'key_personal_effects': 'H', 'key_menu': 'Escape',
}


def bundled_keyboard_prompts(port_dir: Path | None = None) -> Path | None:
    """The keyboard prompt pack the port ships, or None in a copy without it."""
    root = port_dir or PORT_DIR
    for folder in (root / "bundled", root / "packaging" / "windows" / "bundled", root / "mods"):
        candidate = folder / KEYBOARD_PROMPTS
        if (candidate / "menu" / "common.tpf.dcx").is_file():
            return candidate
    return None


def install_keyboard_prompts(mods_dir: Path, port_dir: Path | None = None) -> Path:
    """Copies the bundled keyboard prompts into the mods folder (once). Returns the mod folder."""
    source = bundled_keyboard_prompts(port_dir)
    if source is None:
        raise ValueError(
            tr("Клавиатурные подсказки отсутствуют в дистрибутиве")
        )
    target = Path(mods_dir) / KEYBOARD_PROMPTS
    if not (target / "menu" / "common.tpf.dcx").is_file():
        shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def is_xbox_prompt(name: str) -> bool:
    low = name.lower()
    return "xbox" in low and "prompt" in low


def is_keyboard_prompt(name: str) -> bool:
    low = name.lower()
    return name == KEYBOARD_PROMPTS or ("keyboard" in low and "prompt" in low)


def is_prompt_mod(name: str) -> bool:
    return is_xbox_prompt(name) or is_keyboard_prompt(name)


def canonical_control_scheme(value: str | None, default: str = "xbox") -> str:
    """Normalizes any control scheme string into 'pc', 'xbox', or 'playstation'."""
    if not value or not isinstance(value, str):
        return default
    v = value.strip().lower()
    if v in ("pc", "keyboard", "kb", "kbm", "mouse", "keyboard & mouse", "pc — keyboard & mouse", "пк — клавиатура и мышь"):
        return "pc"
    if v in ("xbox", "xinput", "xbox controller", "геймпад xbox"):
        return "xbox"
    if v in ("playstation", "ps", "ps4", "ps5", "dualshock", "dualsense", "playstation controller", "геймпад playstation"):
        return "playstation"
    return default


def detect_control_scheme(mods_dir: Path, config_file: Path | None = None, fallback: str | None = None) -> str:
    """Detects active scheme from mods.json, or checks fallback/defaults."""
    cfg = Path(config_file) if config_file else None
    if cfg and cfg.is_file():
        try:
            profile = json.loads(cfg.read_text(encoding="utf-8"))
            enabled = set(profile.get("enabled", []))
            disabled = set(profile.get("disabled", []))
            if any(is_keyboard_prompt(n) for n in enabled):
                return "pc"
            if any(is_xbox_prompt(n) for n in enabled):
                return "xbox"
            if any(is_prompt_mod(n) for n in disabled) and not any(is_prompt_mod(n) for n in enabled):
                return "playstation"
        except (OSError, ValueError):
            pass
    if fallback:
        canon = canonical_control_scheme(fallback, default=None)
        if canon:
            return canon
    mods_path = Path(mods_dir)
    try:
        if any(is_xbox_prompt(p.name) for p in mods_path.iterdir() if p.is_dir()):
            return "xbox"
    except OSError:
        pass
    return "playstation"


def apply_control_scheme(scheme: str, mods_dir: Path, config_file: Path,
                         port_dir: Path | None = None,
                         ini_update_fn=None) -> str:
    """Applies control scheme to mods.json and updates prompt mod activation."""
    scheme = canonical_control_scheme(scheme)
    mods_dir = Path(mods_dir)
    config_file = Path(config_file)
    config_file.parent.mkdir(parents=True, exist_ok=True)

    profile = {}
    if config_file.is_file():
        try:
            profile = json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            profile = {}

    enabled = set(profile.get("enabled", []))
    disabled = set(profile.get("disabled", []))

    available = []
    if mods_dir.is_dir():
        available = [p.name for p in mods_dir.iterdir() if p.is_dir()]
    xbox_mods = [m for m in available if is_xbox_prompt(m)]
    kb_mods = [m for m in available if is_keyboard_prompt(m)]

    if scheme == "pc":
        if not kb_mods and KEYBOARD_PROMPTS not in available:
            install_keyboard_prompts(mods_dir, port_dir)
            available = [p.name for p in mods_dir.iterdir() if p.is_dir()]
            kb_mods = [m for m in available if is_keyboard_prompt(m)]
        for name in kb_mods:
            enabled.add(name)
            disabled.discard(name)
        if KEYBOARD_PROMPTS in available:
            enabled.add(KEYBOARD_PROMPTS)
            disabled.discard(KEYBOARD_PROMPTS)
        for name in xbox_mods:
            disabled.add(name)
            enabled.discard(name)
        if ini_update_fn:
            ini_update_fn(KEYBOARD_PROMPT_LAYOUT, mouse_camera=True)

    elif scheme == "xbox":
        for name in kb_mods:
            disabled.add(name)
            enabled.discard(name)
        if KEYBOARD_PROMPTS in enabled:
            disabled.add(KEYBOARD_PROMPTS)
            enabled.discard(KEYBOARD_PROMPTS)
        if xbox_mods:
            enabled.add(xbox_mods[0])
            disabled.discard(xbox_mods[0])
            for extra in xbox_mods[1:]:
                disabled.add(extra)
                enabled.discard(extra)

    elif scheme == "playstation":
        for name in [*kb_mods, *xbox_mods, KEYBOARD_PROMPTS]:
            if name in available or name in enabled or name in disabled:
                disabled.add(name)
                enabled.discard(name)

    profile["enabled"] = sorted(enabled)
    profile["disabled"] = sorted(disabled)
    if "order" in profile:
        profile["order"] = [m for m in profile["order"] if m in available or m in enabled or m in disabled]

    tmp = config_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(config_file)
    return scheme

