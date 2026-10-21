# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared networking, online pool, and environment configuration for Bloodborne PC."""

import json
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.9.7"
CLIENT_VERSION = f"bbport-jgamrot {VERSION}"
COMMUNITY_SERVER = "https://thehuntersdream.com"
HUNTERS_DREAM_POOL = os.environ.get("BB_HUNTERS_DREAM") != "0"
PLAY_MODES = ("offline", "huntersdream", "coop")

PORT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("BB_DATA_DIR", PORT_DIR))

APP_DEFAULTS = {
    "ui_language": "",
    "game_dir": str(PORT_DIR.parent / "CUSA03173"),
    "user_dir": "",
    "dlc_dir": "",
    "mods_dir": "",
    "mods_enabled": True,
    "patches_dir": "",
    "language": "1",
    "player_name": "",
    "fullscreen": False,
    "hdr": False,
    "present_mode": "Mailbox",
    "fps_mode": "uncap",
    "frame_cap": "",
    "draw_pipe": "",
    "readbacks": "",
    "frames_ahead": "",
    "vram_budget_mb": "",
    "frame_stats": False,
    "gpu_profile": False,
    "vk_validation": False,
    "extra_env": "",
    "close_on_play": False,
    "check_updates": False,
    "online": False,
    "online_server": "srv.shadps4.net:31313",
    "online_pool": "huntersdream",
    "online_webapi": "",
    "online_npid": "",
    "online_password": "",
    "online_upnp": True,
    "coop_name": "",
    "coop_password": "",
    "coop_invite": "",
    "online_community": COMMUNITY_SERVER,
    "play_mode": "",
    "thd_online_id": "",
    "thd_token": "",
}


def https_context():
    """System trusted roots plus certifi if present."""
    context = ssl.create_default_context()
    try:
        import certifi
        context.load_verify_locations(certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        pass
    return context


def connection_error_text(error):
    """Format connection error, noting date/time/proxy if certificate verify failed."""
    text = str(error)
    if "CERTIFICATE_VERIFY_FAILED" in text:
        text += (". Check that the PC's date and time are right; HTTPS scanning in an "
                 "antivirus or a proxy can also cause this")
    return text


def community_address(value):
    """The game server as https://host, The Hunter's Dream by default."""
    value = str(value).strip() or COMMUNITY_SERVER
    scheme, _sep, rest = value.rpartition("://")
    host = rest.split("/")[0].split(":")[0]
    return f"{scheme or 'https'}://{host}"


def play_mode(s):
    mode = s.get("play_mode")
    if mode in PLAY_MODES:
        return mode
    return "huntersdream" if s.get("online") and s.get("online_pool") == "huntersdream" else "offline"


def hunters_dream_selected(s):
    return HUNTERS_DREAM_POOL and s.get("online_pool") == "huntersdream"


def webapi_address(server):
    host = server.split("://", 1)[-1].split("/")[0].split(":")[0]
    return f"http://{host}:31315"


def webapi_setting(s):
    webapi = str(s.get("online_webapi", "")).strip()
    community_host = community_address(s.get("online_community", "")).split("://", 1)[1].split(":")[0]
    if webapi and community_host in webapi:
        webapi = ""
    return webapi or webapi_address(str(s.get("online_server", "")).strip() or APP_DEFAULTS["online_server"])


def thd_call(url, body):
    """Call The Hunter's Dream account service."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10, context=https_context()) as response:
            text = response.read()
    except urllib.error.HTTPError as error:
        text = error.read()
    try:
        reply = json.loads(text)
    except (ValueError, TypeError):
        reply = None
    if not isinstance(reply, dict) or "ResKind" not in reply:
        raise ValueError(f"{url} has no account service")
    if reply["ResKind"] != 0:
        raise ValueError(reply.get("Message") or "refused")
    return reply


def thd_sign_in(game_server, on_code, cancelled=lambda: False):
    """Discord sign-in flow for The Hunter's Dream account linking."""
    auth = community_address(game_server)
    start = thd_call(auth + "/auth/device/start",
                     {"DeviceName": f"bbport-jgamrot on {os.environ.get('HOSTNAME', os.environ.get('COMPUTERNAME', 'Linux'))}"})
    device, user_code = start.get("DeviceCode", ""), start.get("UserCode", "")
    if not device or not user_code:
        raise ValueError("no code in the reply")
    interval = max(1, int(start.get("Interval") or 5))
    deadline = time.monotonic() + int(start.get("ExpiresIn") or 600)
    page = start.get("VerificationUri") or auth + "/link"
    on_code(page + ("&" if "?" in page else "?") + "code=" + urllib.parse.quote(user_code), user_code)
    while time.monotonic() < deadline and not cancelled():
        time.sleep(interval)
        poll = thd_call(auth + "/auth/device/poll", {"DeviceCode": device})
        status = poll.get("Status")
        if status == "approved":
            if not poll.get("OnlineId") or not poll.get("Token"):
                raise ValueError("no token in the reply")
            return poll["OnlineId"], poll["Token"]
        if status == "slow_down":
            interval += 5
        elif status == "denied":
            raise ValueError("the sign-in was denied")
        elif status == "expired":
            break
    raise ValueError("the sign-in was cancelled" if cancelled() else "the code expired; try again")


def game_environment(s):
    """Construct environment variables for game launch."""
    env = dict(os.environ)
    env["BB_PORT_VERSION"] = VERSION
    env["BB_CLIENT_VERSION"] = CLIENT_VERSION
    env["BB_GAME_DIR"] = s["game_dir"]
    if s.get("user_dir"):
        env["BB_USER_DIR"] = s["user_dir"]
    if s.get("dlc_dir"):
        env["BB_DLC_DIR"] = s["dlc_dir"]
    env["BB_MODS_DIR"] = s.get("mods_dir") or str(DATA_DIR / "mods")
    env["BB_MODS_CONFIG"] = str(DATA_DIR / "mods.json")
    env["BB_MODS_ENABLED"] = "1" if s.get("mods_enabled") else "0"
    env["BB_PATCHES_DIR"] = s.get("patches_dir") or str(DATA_DIR / "patches")
    env["BB_PATCHES_CONFIG"] = str(DATA_DIR / "patches.json")
    env["BB_LANGUAGE"] = str(s.get("language", "1"))
    if str(s.get("player_name", "")).strip():
        env["BB_USER_NAME"] = str(s["player_name"]).strip()
    env["BB_FULLSCREEN"] = "1" if s.get("fullscreen") else "0"
    env["BB_PRESENT_MODE"] = s.get("present_mode", "Mailbox")
    if s.get("hdr"):
        env["BB_HDR"] = "1"
    env["BB_FPS"] = s.get("fps_mode", "uncap")
    if s.get("frame_cap"):
        env["BB_FPS_LIMIT"] = str(s["frame_cap"])
    if s.get("draw_pipe"):
        env["BB_DRAW_PIPE"] = str(s["draw_pipe"])
    if s.get("readbacks"):
        env["BB_READBACKS"] = str(s["readbacks"])
    if s.get("frames_ahead") not in (None, ""):
        # 0 means no bound, so it must be exported too.
        env["BB_FRAMES_AHEAD"] = str(s["frames_ahead"])
    if s.get("vram_budget_mb"):
        env["BB_GC_BUDGET_MB"] = str(s["vram_budget_mb"])
    for key, name in (("frame_stats", "BB_FRAME_STATS"), ("gpu_profile", "BB_GPU_PROFILE"),
                      ("vk_validation", "BB_VK_VALIDATION")):
        if s.get(key):
            env[name] = "1"
    for item in str(s.get("extra_env", "")).split():
        if "=" in item:
            k, v = item.split("=", 1)
            env[k] = v

    if s.get("online") and play_mode(s) == "huntersdream":
        server = str(s.get("online_server", "")).strip() or APP_DEFAULTS["online_server"]
        env["BB_ONLINE"] = "1"
        env["BB_SHADNET_SERVER"] = server
        env["BB_SHADNET_WEBAPI"] = webapi_setting(s)
        env["BB_SHADNET_NPID"] = str(s.get("online_npid", "")).strip()
        env["BB_SHADNET_PASSWORD"] = str(s.get("online_password", ""))
        env["BB_UPNP"] = "1" if s.get("online_upnp") else "0"
        env["BB_COMMUNITY_SERVER"] = community_address(s.get("online_community", ""))
        if hunters_dream_selected(s):
            env["BB_NET_BACKEND"] = "thd"
            env["BB_THD_ONLINE_ID"] = str(s.get("thd_online_id", ""))
            env["BB_THD_TOKEN"] = str(s.get("thd_token", ""))
            for key in ("BB_SHADNET_SERVER", "BB_SHADNET_WEBAPI", "BB_SHADNET_NPID", "BB_SHADNET_PASSWORD"):
                env.pop(key, None)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env
