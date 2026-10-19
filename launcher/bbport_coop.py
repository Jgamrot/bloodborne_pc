"""Seamless co-op (experimental): BBSC by CLS_AMG, set up and run from the launcher.

BBSC (Bloodborne Seamless Co-op, https://github.com/Classmg22/BBSC, GPL-2.0-or-later) keeps a
co-op session alive through deaths, lamps, areas and bosses for up to five hunters. It needs a
server: the host's PC runs BBSC's two server programs (shadnet.exe, from Wozzardman's
shadnet-p2p, and BBSC-GameServer.exe) and the guests reach it over Tailscale (or the same home
network). The game runs with BBSC's DLL through bbsc-launch.exe, which BBSC's own BBport package
puts in BB_PROBE's place.

Nothing of BBSC is shipped with the port: its official release packages are downloaded on demand,
checked against the release's published SHA-256, and unpacked under %LOCALAPPDATA%\\bbport-coop.
Normal play and normal online are unchanged: co-op settings only reach the game started by
co_op_environment(), and run.py writes the server redirects for that one launch.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

REPO = 'Classmg22/BBSC'
RELEASES = f'https://github.com/{REPO}/releases'
DISCORD = 'https://discord.gg/Df7BCmfWdt'
# (release tag, asset, folder inside the zip): the BBport package of the newest release and the
# server package (only published with 0.0.1).
PACKAGES = {
    'client': ('0.0.1_hotfix', 'BBSC-0.0.1-BBport.zip', 'BBSC-0.0.1-BBport'),
    'server': ('v0.0.1', 'BBSC-0.0.1-Server.zip', 'BBSC-0.0.1-Server'),
}
SHADNET_PORT, MATCHING_PORT, WEBAPI_PORT, GAME_PORT, RELAY_PORT = 31313, 31314, 31315, 20443, 20444
INVITE_PREFIX = 'BBCOOP-'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# Tailscale's own address on every tailnet: a route to it goes out through the Tailscale adapter.
TAILSCALE_DNS = '100.100.100.100'
# Inbound rules: the server ports, and the game itself (the host's game takes the guests'
# connections). Tailscale's range and this PC's own networks only - nothing opens to the internet.
FIREWALL_RANGES = ('100.64.0.0/10', 'LocalSubnet')
FIREWALL_PORTS = (('shadnet', 'TCP', SHADNET_PORT), ('matching', 'UDP', MATCHING_PORT),
                  ('webapi', 'TCP', WEBAPI_PORT), ('game server', 'TCP', GAME_PORT),
                  ('relay', 'TCP', RELAY_PORT), ('sessions', 'TCP', 18671), ('STUN', 'UDP', 3478))
RULE_PREFIX = 'Bloodborne co-op'


class CoopError(Exception):
    pass


def coop_dir():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'bbport-coop'


def package_dir(kind):
    return coop_dir() / PACKAGES[kind][2]


def installed(kind):
    folder = package_dir(kind)
    if kind == 'client':
        return all((folder / p).is_file() for p in ('bbsc/bbsc-launch.exe', 'bbsc/bbsc.dll',
                                                     'account/shadnet-sample.exe'))
    return all((folder / 'server' / p).is_file() for p in ('shadnet.exe', 'BBSC-GameServer.exe',
                                                            'shadnet.cfg'))


# --- Download -------------------------------------------------------------------------------------

def _release_asset(tag, name):
    request = urllib.request.Request(f'https://api.github.com/repos/{REPO}/releases/tags/{tag}',
                                     headers={'User-Agent': 'bbport-launcher',
                                              'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as reply:
        release = json.load(reply)
    for asset in release.get('assets', []):
        if asset.get('name') == name:
            digest = str(asset.get('digest') or '')
            if not digest.startswith('sha256:'):
                raise CoopError(f'{name}: the release publishes no SHA-256 to check it against.')
            return asset['browser_download_url'], digest.split(':', 1)[1].lower()
    raise CoopError(f'{name} is not in BBSC release {tag} any more ({RELEASES}).')


def _safe_extract(archive, destination):
    root = destination.resolve()
    for member in archive.infolist():
        target = (destination / member.filename).resolve()
        if root != target and root not in target.parents:
            raise CoopError(f'Unsafe path in the package: {member.filename}')
    archive.extractall(destination)


def download(kind, progress=None):
    """Downloads and unpacks one BBSC package; the server package keeps an existing database,
    registration key and logs."""
    tag, name, folder = PACKAGES[kind]
    url, expected = _release_asset(tag, name)
    coop_dir().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.bbsc-', dir=coop_dir()) as temporary:
        zip_path = Path(temporary) / name
        digest = hashlib.sha256()
        request = urllib.request.Request(url, headers={'User-Agent': 'bbport-launcher'})
        with urllib.request.urlopen(request, timeout=60) as reply, open(zip_path, 'wb') as out:
            total = int(reply.headers.get('Content-Length') or 0)
            done = 0
            while chunk := reply.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress and total:
                    progress(f'Downloading {name}: {done * 100 // total}%')
        if digest.hexdigest() != expected:
            raise CoopError(f'{name} does not match the checksum BBSC published; not installed.')
        staging = Path(temporary) / 'unpacked'
        with zipfile.ZipFile(zip_path) as archive:
            _safe_extract(archive, staging)
        new = staging / folder
        old = package_dir(kind)
        if kind == 'server' and old.is_dir():
            # The host's own data survives an update of the programs.
            for keep in ('server/shadnet.cfg', 'server/db', 'server/logs'):
                if (old / keep).exists():
                    target = new / keep
                    if target.is_dir():
                        shutil.rmtree(target)
                    elif target.exists():
                        target.unlink()
                    shutil.move(str(old / keep), str(target))
        if old.exists():
            shutil.rmtree(old)
        shutil.move(str(new), str(old))
    return package_dir(kind)


# --- Network ---------------------------------------------------------------------------------------

def tailscale_exe():
    """tailscale.exe: on PATH (the installer adds it, wherever it was installed), else the default folder."""
    found = shutil.which('tailscale')
    if found:
        return Path(found)
    for variable in ('ProgramW6432', 'ProgramFiles'):
        folder = os.environ.get(variable)
        if folder and (Path(folder) / 'Tailscale' / 'tailscale.exe').is_file():
            return Path(folder) / 'Tailscale' / 'tailscale.exe'
    return None


def tailscale_ip():
    return _tailscale_ip_from_cli() or _tailscale_ip_from_route()


def _tailscale_ip_from_cli():
    exe = tailscale_exe()
    if not exe:
        return None
    try:
        out = subprocess.run([str(exe), 'ip', '-4'], capture_output=True, text=True,
                             timeout=10, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.split():
        if is_tailscale(line):
            return line
    return None


def _tailscale_ip_from_route():
    """This PC's address on the Tailscale adapter, when the CLI can't be run (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect((TAILSCALE_DNS, 9))
            ip = probe.getsockname()[0]
        except OSError:
            return None
    return ip if is_tailscale(ip) else None


def is_tailscale(address):
    parts = address.split('.')
    return len(parts) == 4 and parts[0] == '100' and parts[1].isdigit() and 64 <= int(parts[1]) <= 127


def local_ip():
    """This PC's address on its home network (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(('192.0.2.1', 9))
            return probe.getsockname()[0]
        except OSError:
            return None


def host_address():
    """(address, network name): Tailscale when it is connected, else the home network."""
    ip = tailscale_ip()
    if ip:
        return ip, 'Tailscale'
    ip = local_ip()
    if ip:
        return ip, 'your home network only (Tailscale is not connected)'
    return None, None


# --- One-time setup (one administrator prompt) ---------------------------------------------------

def _firewall_script(game_exe):
    ranges = ','.join(f"'{r}'" for r in FIREWALL_RANGES)
    lines = ['$ErrorActionPreference = "Continue"', f'$ranges = @({ranges})']
    for label, protocol, port in FIREWALL_PORTS:
        rule = f'{RULE_PREFIX} {label} {port}'
        lines.append(f"Remove-NetFirewallRule -DisplayName '{rule}' -ErrorAction SilentlyContinue")
        lines.append(f"New-NetFirewallRule -DisplayName '{rule}' -Direction Inbound -Protocol {protocol} "
                     f"-LocalPort {port} -RemoteAddress $ranges -Action Allow | Out-Null")
    rule = f'{RULE_PREFIX} game'
    lines.append(f"Remove-NetFirewallRule -DisplayName '{rule}' -ErrorAction SilentlyContinue")
    lines.append(f"New-NetFirewallRule -DisplayName '{rule}' -Direction Inbound -Program '{game_exe}' "
                 "-RemoteAddress $ranges -Action Allow | Out-Null")
    redist = package_dir('server') / 'server' / 'vc_redist.x64.exe'
    lines.append("$key = 'HKLM:\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64'")
    lines.append(f"if (-not ((Test-Path $key) -and (Get-ItemProperty $key).Installed -eq 1) -and "
                 f"(Test-Path '{redist}')) {{ Start-Process '{redist}' -ArgumentList '/install /quiet /norestart' -Wait }}")
    return '\r\n'.join(lines) + '\r\n'


def setup_done(game_exe):
    command = (f"$r = Get-NetFirewallRule -DisplayName '{RULE_PREFIX} game' -ErrorAction SilentlyContinue; "
               f"if ($r -and (($r | Get-NetFirewallApplicationFilter).Program -eq '{game_exe}')) {{ exit 0 }} else {{ exit 1 }}")
    try:
        return subprocess.run(['powershell', '-NoProfile', '-Command', command], timeout=30,
                              creationflags=NO_WINDOW).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run_setup(game_exe):
    """Firewall rules (Tailscale and home network only) and the C++ runtime the servers need.
    Windows asks the player once for administrator rights."""
    script = coop_dir() / 'setup-firewall.ps1'
    coop_dir().mkdir(parents=True, exist_ok=True)
    script.write_text(_firewall_script(game_exe), encoding='utf-8-sig')
    command = (f"Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
               f"'-NoProfile -ExecutionPolicy Bypass -File \"{script}\"'")
    result = subprocess.run(['powershell', '-NoProfile', '-Command', command], creationflags=NO_WINDOW)
    if result.returncode != 0 or not setup_done(game_exe):
        raise CoopError('Setup needs the Yes on the Windows prompt. Try Start hosting again.')


# --- Hosting -----------------------------------------------------------------------------------------

# This port's build of the co-op shadNet server (packaging/windows/build_coop_server.sh):
# Wozzardman's shadnet-p2p with one patch, so clients on shadPS4 0.20's network code (this port
# since 1.9.5) get STUN replies; BBSC's own shadnet.exe drops their signaling packets. BBSC's game
# server is used as it is.
PORT_DIR = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parent.parent)


def bundled_server():
    for folder in (PORT_DIR / 'bin' / 'coop-server', PORT_DIR / 'out' / 'coop-server'):
        if (folder / 'shadnet.exe').is_file():
            return folder
    return None


def shadnet_dir(sync=False):
    """The folder shadnet.exe runs from. It keeps shadnet.cfg and its database beside itself, so
    this port's server runs from its own folder under bbport-coop, which updates leave alone.
    sync (only while the server is stopped): copy the bundled programs there, and BBSC's
    configuration (ports, seamless co-op, the host's registration key) the first time."""
    bundled = bundled_server()
    if bundled is None:
        return package_dir('server') / 'server'
    target = coop_dir() / 'shadnet-bbport'
    if sync:
        for source in bundled.rglob('*'):
            if not source.is_file():
                continue
            copy = target / source.relative_to(bundled)
            if (not copy.is_file() or copy.stat().st_size != source.stat().st_size
                    or copy.stat().st_mtime < source.stat().st_mtime):
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, copy)
        bbsc = package_dir('server') / 'server'
        for name in ('shadnet.cfg', 'worlds.cfg', 'scoreboards.cfg'):
            if not (target / name).exists() and (bbsc / name).is_file():
                shutil.copy2(bbsc / name, target / name)
    return target


def registration_key():
    """The host's own key (created on first use): only players who have it can make accounts."""
    cfg = shadnet_dir() / 'shadnet.cfg'
    if not cfg.is_file():
        cfg = shadnet_dir(sync=True) / 'shadnet.cfg'
    text = cfg.read_text(encoding='utf-8')
    for line in text.splitlines():
        if line.startswith('RegistrationSecretKey='):
            value = line.split('=', 1)[1].strip()
            if value:
                return value
            key = secrets.token_hex(20)
            cfg.write_text(text.replace(line, f'RegistrationSecretKey={key}'), encoding='utf-8')
            return key
    key = secrets.token_hex(20)
    cfg.write_text(text.rstrip('\n') + f'\nRegistrationSecretKey={key}\n', encoding='utf-8')
    return key


class Host:
    """The two server programs while this launcher hosts."""

    def __init__(self):
        self.processes = []
        self.address = None

    @property
    def running(self):
        return any(p.poll() is None for p in self.processes)

    def start(self, address):
        self.stop()
        server = package_dir('server') / 'server'
        shadnet = shadnet_dir()
        # Servers left over from a launcher that closed without stopping them hold the ports.
        end_leftovers(server)
        if shadnet != server:
            end_leftovers(shadnet)
        shadnet = shadnet_dir(sync=True)
        logs = server / 'logs'
        logs.mkdir(exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        env = dict(os.environ, SHADNET_BLOODBORNE_SEAMLESS_COOP='1')
        shadnet_log = open(logs / f'shadnet-{stamp}.log', 'w', encoding='utf-8', errors='replace')
        self.processes.append(subprocess.Popen([str(shadnet / 'shadnet.exe')], cwd=shadnet, env=env,
                                               stdout=shadnet_log, stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL, creationflags=NO_WINDOW))
        time.sleep(2)
        game_log = open(logs / f'gameserver-{stamp}.log', 'w', encoding='utf-8', errors='replace')
        self.processes.append(subprocess.Popen(
            [str(server / 'BBSC-GameServer.exe'), '--shadnet', address, '--host', '0.0.0.0',
             '--advertise', address, '--summon-interval', '5', '--no-playlog', '--log-dir', str(logs)],
            cwd=server, stdout=game_log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=NO_WINDOW))
        time.sleep(1)
        if not self.running or any(p.poll() is not None for p in self.processes):
            self.stop()
            raise CoopError(f'A co-op server stopped at start; see {logs}.')
        self.address = address

    def stop(self):
        for process in self.processes:
            if process.poll() is None:
                end_tree(process)
        self.processes = []
        self.address = None


def end_tree(process):
    """BBSC-GameServer.exe runs a second copy of itself as a child: end the whole tree, or the
    child keeps the ports after Stop hosting."""
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                       creationflags=NO_WINDOW)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def end_leftovers(server):
    """Ends shadnet.exe and BBSC-GameServer.exe processes started from this server folder."""
    if os.name != 'nt':
        return
    folder = str(Path(server).resolve()).replace("'", "''")
    script = (f"Get-CimInstance Win32_Process | Where-Object {{ $_.ExecutablePath -and "
              f"$_.ExecutablePath.StartsWith('{folder}\\', 'OrdinalIgnoreCase') }} | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                   capture_output=True, creationflags=NO_WINDOW)


# --- Invites and accounts ------------------------------------------------------------------------

def make_invite(address, key):
    data = json.dumps({'a': address, 'k': key}, separators=(',', ':')).encode()
    return INVITE_PREFIX + base64.urlsafe_b64encode(data).decode().rstrip('=')


def read_invite(code):
    # Chat apps wrap long codes over lines and add spaces: none belong to the code.
    code = ''.join(code.split())
    if not code.startswith(INVITE_PREFIX):
        raise CoopError(f'An invite code starts with {INVITE_PREFIX}')
    body = code[len(INVITE_PREFIX):]
    try:
        data = json.loads(base64.urlsafe_b64decode(body + '=' * (-len(body) % 4)))
        address, key = str(data['a']), str(data.get('k', ''))
    except (ValueError, KeyError, TypeError):
        raise CoopError('That invite code is damaged; ask the host to copy it again.') from None
    return address, key


def _account_tool(address, *arguments):
    tool = package_dir('client') / 'account' / 'shadnet-sample.exe'
    if not tool.is_file():
        raise CoopError('Set up co-op first (the BBSC package is missing).')
    try:
        result = subprocess.run([str(tool), address, str(SHADNET_PORT), *arguments], capture_output=True,
                                text=True, timeout=30, cwd=tool.parent, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise CoopError(f'No answer from the co-op server at {address}. Is the host hosting, '
                        'and are you both on Tailscale?') from None
    return (result.stdout or '') + (result.stderr or '')


def create_account(address, key, name, password):
    """Creates the account on the host's server, then checks it signs in. An existing account
    (the same name and password) only gets the check."""
    if not (3 <= len(name) <= 16 and all(c.isalnum() or c in '-_' for c in name)):
        raise CoopError('A co-op name is 3-16 letters, numbers, - or _.')
    if len(password) < 4:
        raise CoopError('Choose a password of at least 4 characters (one you use nowhere else).')
    out = _account_tool(address, 'login', name, password)
    if '[login] OK' in out:
        return 'signed in'
    arguments = ['register', name, password, f'{name}@bbport-coop.invalid']
    if key:
        arguments.append(key)
    out = _account_tool(address, *arguments)
    if 'Account created successfully' not in out:
        raise CoopError('The host\'s server did not create the account (the name may be taken, or '
                        'the invite is from another host).')
    if '[login] OK' not in _account_tool(address, 'login', name, password):
        raise CoopError('The account was created but does not sign in; try another name.')
    return 'created'


# --- The game ------------------------------------------------------------------------------------

def co_op_environment(env, address, name, password, probe, save_copy=None):
    """The normal game environment, pointed at the host's servers with BBSC loaded. run.py writes
    this launch's server redirects (user/host_overrides.json) from these values."""
    launcher = package_dir('client') / 'bbsc' / 'bbsc-launch.exe'
    # BBSC's own redirect (its play-bbport.ps1): the game server and the summon messenger the
    # BBSC game server's server info names, both on the host.
    overrides = coop_dir() / 'host_overrides.json'
    overrides.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({
        'https://ss4.scej-network.jp:20443': f'http://{address}:{GAME_PORT}',
        'http://thehuntersdream.com:18671/summon_messenger': f'http://{address}:{WEBAPI_PORT}',
        'https://thehuntersdream.com:18671/summon_messenger': f'http://{address}:{WEBAPI_PORT}',
    }, indent=2) + '\n'
    overrides.write_text(text, encoding='utf-8')
    # BBSC reads the same file itself, but only from <folder the game starts in>\user (run.py
    # starts it in the port's folder), its exe's folder\user or %APPDATA%\shadPS4. Every normal
    # online launch rewrites the port's user\host_overrides.json, so this copy serves this
    # co-op launch only.
    port_user = Path(probe).resolve().parent.parent / 'user'
    port_user.mkdir(parents=True, exist_ok=True)
    (port_user / 'host_overrides.json').write_text(text, encoding='utf-8')
    env = dict(env)
    # Co-op runs on the shadNet backend against the host's servers, never The Hunter's Dream's,
    # whatever pool the main online settings choose (run.py drops these again for BB_COOP=1).
    for key in ('BB_NET_BACKEND', 'BB_THD_TOKEN', 'BB_THD_ONLINE_ID', 'BB_THD_SERVER', 'BB_THD_AUTH',
                'BB_THD_RULESET'):
        env.pop(key, None)
    # BBSC's co-op kit (its Hunt Bell, Kin Bell and the rest, which replace the vanilla bells) is
    # only given after BBSC has copied the save folder BBSC_SAVE_DIR names (BBSC's
    # BackupBbscSaves; it finds saves only in shadPS4's layout otherwise). Copying the save the
    # running game has open failed every time, so the kit never came and a new character had no
    # bell to start co-op with. BBSC gets the copy this launcher made just before the session
    # (`save_copy`, backup_saves), which nothing has open; the bells still go into the live save.
    save_dir = (active_save_dir(save_copy) if save_copy else None) or \
        active_save_dir(Path(env.get('BB_USER_DIR') or port_user))
    if save_dir:
        env['BBSC_SAVE_DIR'] = str(save_dir)
    env.update({
        'BBSC_RELAY': f'{address}:{RELAY_PORT}',  # BBSC's relay (warps, world sync) on the host
        'BB_PROBE': str(launcher),
        'BBSC_EMULATOR': str(probe),
        'BB_ONLINE': '1',
        'BB_SHADNET_SERVER': f'{address}:{SHADNET_PORT}',
        'BB_SHADNET_WEBAPI': f'http://{address}:{WEBAPI_PORT}',
        'BB_HOST_OVERRIDES': str(overrides),
        'BB_SHADNET_NPID': name,
        'BB_SHADNET_PASSWORD': password,
        'BB_USER_NAME': name,
        'BB_COOP': '1',
    })
    return env


def active_save_dir(user_dir):
    """The game's save folder (SPRJ0005, userdata0000...) written most recently, or None."""
    newest = None
    for folder in Path(user_dir).glob('savedata/*/CUSA00207/SPRJ0005'):
        times = [f.stat().st_mtime for f in folder.glob('userdata00*') if f.is_file()]
        if times and (newest is None or max(times) > newest[0]):
            newest = (max(times), folder)
    return newest[1] if newest else None


def backup_saves(user_dir):
    """A copy of the saves before every co-op session (BBSC 0.0.1 is a first test)."""
    saves = Path(user_dir) / 'savedata'
    if not saves.is_dir():
        return None
    target = Path(user_dir) / 'coop-backups' / time.strftime('%Y%m%d-%H%M%S') / 'savedata'
    shutil.copytree(saves, target)
    return target.parent
