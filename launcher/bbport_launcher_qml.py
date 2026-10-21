"""Qt Quick front end for the Windows Bloodborne launcher."""
import os
from pathlib import Path
import sys

import bbport_launcher_win as launcher_core

# Must run before PySide6/Qt creates the QQuickWindow: Wine's D3D11 path does not present
# QML page changes until a resize. Native Windows is unaffected.
launcher_core.configure_renderer()

from PySide6.QtCore import QTimer, QUrl, qInstallMessageHandler
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from bbport_launcher_backend import LauncherBackend
import bbport_startup


def _qt_message(_mode, _context, message):
    """BB_LAUNCHER_DEBUG=1: QML/runtime warnings go to the launcher diagnostics file."""
    launcher_core.debug_log(f'Qt: {message}')


qInstallMessageHandler(_qt_message)

# How long the "Launching Bloodborne" toast stays up if the game does not report running sooner.
SPLASH_MS = 8000
# A direct launch waits this long first, so Shift or a click on the toast can still open the
# launcher instead (issue #11: the game started too soon to notice the hint).
GRACE_S = 3


def log_window(window, label):
    """BB_LAUNCHER_DEBUG=1: window size/visibility and a few frame counters, not per-frame."""
    screen = window.screen()
    launcher_core.debug_log(
        f'{label}: size={window.width()}x{window.height()} geometry={window.geometry()!r} '
        f'visibility={window.visibility()} active={window.isActive()} '
        f'dpr={window.devicePixelRatio()} screen={screen.geometry()!r}' if screen else
        f'{label}: size={window.width()}x{window.height()} geometry={window.geometry()!r} '
        f'visibility={window.visibility()} active={window.isActive()} '
        f'dpr={window.devicePixelRatio()} screen=None')
    frames = [0]
    api_logged = [False]

    def frame_swapped():
        frames[0] += 1
        page = window.property('page')
        exposed = window.isExposed() if hasattr(window, 'isExposed') else '?'
        if frames[0] <= 600:  # BB_LAUNCHER_DEBUG: enough for a transition test, not unbounded
            launcher_core.debug_log(
                f'{label}: frame {frames[0]} page={page!r} size={window.width()}x{window.height()} '
                f'visibility={window.visibility()} active={window.isActive()} exposed={exposed}')
        if not api_logged[0]:
            api_logged[0] = True
            try:
                interface = window.rendererInterface()
                api = interface.graphicsApi() if interface is not None else None
            except (AttributeError, RuntimeError):
                api = None
            launcher_core.debug_log(f'{label}: graphicsApi={api!r} renderLoop={os.environ.get("QSG_RENDER_LOOP")!r} '
                                    f'rhi={os.environ.get("QSG_RHI_BACKEND")!r} quick={os.environ.get("QT_QUICK_BACKEND")!r}')

    frame_swapped_signal = getattr(window, 'frameSwapped', None)
    if frame_swapped_signal is not None:
        frame_swapped_signal.connect(frame_swapped)
    for name in ('widthChanged', 'heightChanged', 'visibleChanged', 'activeChanged', 'visibilityChanged'):
        signal = getattr(window, name, None)
        if signal is not None:
            signal.connect(lambda *args, event=name: launcher_core.debug_log(
                f'{label}: {event} size={window.width()}x{window.height()} '
                f'visibility={window.visibility()} active={window.isActive()}'))


def run_ui(route=None):
    """ROUTE comes from bbport_startup.route(); without one the launcher opens on Home."""
    launcher_core.debug_log(f'run_ui route={route!r}')
    QQuickStyle.setStyle('Basic')
    app = QApplication(sys.argv)
    app.setApplicationName('Bloodborne')
    icon_path = (Path(sys.executable).resolve().parent / 'launcher' / 'assets' / 'hunter-icon.ico') if getattr(sys, 'frozen', False) else (Path(__file__).resolve().parent / 'assets' / 'hunter-icon.ico')
    app.setWindowIcon(QIcon(str(icon_path)))
    backend = LauncherBackend(route)
    backend.connect_workers()
    engine = QQmlApplicationEngine()
    engine.warnings.connect(lambda warnings: [launcher_core.debug_log(f'QML warning: {warning}')
                                               for warning in warnings])
    engine.rootContext().setContextProperty('launcher', backend)
    qml = Path(__file__).resolve().parent / 'qml'
    if getattr(sys, 'frozen', False):
        import bbport_launcher_win as core
        qml = core.PORT_DIR / 'launcher' / 'qml'

    def load(name):
        loaded = len(engine.rootObjects())
        engine.load(QUrl.fromLocalFile(str(qml / name)))
        if len(engine.rootObjects()) == loaded:
            raise RuntimeError(f'Could not load Qt Quick launcher: {qml / name}')
        return engine.rootObjects()[-1]

    launcher_window = []

    def open_launcher(page=None, step=0):
        if launcher_window:
            return
        if page:
            backend.open_at(page, step)
        launcher_core.debug_log(f'open_launcher page={page!r} step={step} startPage={backend.startPage!r}')
        backend.start_background_checks()
        window = load('Main.qml')
        launcher_window.append(window)
        log_window(window, 'Main.qml')
        backend.closeRequested.connect(window.close)
        app.aboutToQuit.connect(backend.shutdown_coop)
        app.setQuitOnLastWindowClosed(True)

    if not route or route['mode'] != 'direct':
        open_launcher()
        return app.exec()

    # Direct launch: no launcher window, only a toast while the game starts. Shift/Ctrl or a
    # click on the toast opens the launcher; so does a game that fails before it is running.
    app.setQuitOnLastWindowClosed(False)
    splash = load('Splash.qml')
    log_window(splash, 'Splash.qml')
    keys = QTimer()
    keys.setInterval(100)

    def close_splash():
        keys.stop()
        countdown.stop()
        splash.close()

    def show_launcher(page='Home'):
        close_splash()
        open_launcher(page)

    def check_keys():
        if bbport_startup.launcher_keys_held():
            show_launcher()

    def finished(code, started):
        launcher_core.debug_log(f'finished code={code} started={started} launcher_open={bool(launcher_window)}')
        close_splash()
        if launcher_window:
            return  # the launcher is open; the user decides when to quit
        if started or code == 0:
            app.quit()
        else:
            open_launcher('Log')

    def start():
        if launcher_window:
            return  # the player chose the launcher during the countdown
        launcher_core.debug_log('direct start: backend.play()')
        close_timer.start()
        backend.play()
        if not backend.running:  # refused or could not start; the notice says why
            show_launcher()

    keys.timeout.connect(check_keys)
    # The update check waits until the game is running and only remembers what it finds.
    backend.gameStarted.connect(lambda: launcher_core.start_quiet_update_check(backend.app))
    splash.openLauncher.connect(show_launcher)
    backend.gameStarted.connect(close_splash)
    backend.gameFinished.connect(finished)
    keys.start()
    close_timer = QTimer()
    close_timer.setSingleShot(True)
    close_timer.setInterval(SPLASH_MS)
    close_timer.timeout.connect(close_splash)
    remaining = [GRACE_S]
    countdown = QTimer()
    countdown.setInterval(1000)

    def tick():
        remaining[0] -= 1
        splash.setProperty('countdown', remaining[0])
        if remaining[0] <= 0:
            countdown.stop()
            start()

    countdown.timeout.connect(tick)
    splash.setProperty('countdown', GRACE_S)
    if GRACE_S > 0:
        countdown.start()
    else:
        QTimer.singleShot(0, start)
    return app.exec()

if __name__ == "__main__":
    sys.exit(run_ui())
