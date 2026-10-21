import QtQuick
import QtQuick.Controls

ApplicationWindow {
    id: window
    visible: true
    width: 1360; height: 860
    minimumWidth: 1100; minimumHeight: 700
    title: "Bloodborne — Windows"
    color: Theme.base
    property string page: "Home"
    property int wizardStep: 0
    property string searchQuery: ""
    property var checks: launcher.readiness
    property bool gameBlocked: checks.length > 0 && checks[0].level === "error"
    property bool savesBlocked: (checks.length > 2 && checks[2].level === "error") || !launcher.savesWritable
    property bool onlineBlocked: launcher.playModeBlocked
    property bool blocked: gameBlocked || savesBlocked || onlineBlocked || launcher.setupRunning
    property bool settingsPage: ["Graphics", "Display", "Game", "Mods", "Online", "System"].indexOf(page) >= 0
    onPageChanged: {
        launcher.debugPage("page=" + page + " size=" + width + "x" + height)
        if (settingsPage !== true) searchQuery = ""
    }

    function pageTitle() {
        switch (page) {
        case "Graphics": return "Graphics"
        case "Display": return "Display"
        case "Game": return "Game & saves"
        case "Mods": return "Mods & patches"
        case "Online": return "Online"
        case "System": return "System"
        case "Logs": return "Diagnostics"
        case "Setup": return "Setup"
        default: return "Overview"
        }
    }
    function pageSubtitle() {
        switch (page) {
        case "Graphics": return "Upscaling, effects and frame generation"
        case "Display": return "Output, frame pacing and presentation"
        case "Game": return "Game files, saves and input"
        case "Mods": return "Enhancements, mods and patches"
        case "Online": return "The Hunter's Dream and seamless co-op"
        case "System": return "Startup, engine and maintenance"
        case "Logs": return "Runtime status and session log"
        case "Setup": return "First-time configuration"
        default: return "Launch and current configuration"
        }
    }
    function stateText() {
        switch (launcher.launchState) {
        case "preparing": return "Preparing"
        case "starting": return "Starting"
        case "running": return "Running"
        case "failed": return "Failed"
        default: return "Ready"
        }
    }
    function stateColor() {
        switch (launcher.launchState) {
        case "preparing": case "starting": return Theme.warn
        case "running": return Theme.good
        case "failed": return Theme.accent
        default: return Theme.good
        }
    }
    function openPage(name) {
        page = name
        if (name !== "Home" && name !== "Logs" && name !== "Setup") searchQuery = ""
    }
    function openSettingsPage(pageName, category, section, key) {
        page = pageName
        searchQuery = ""
        Qt.callLater(function() { settings.openAt(category, section, key || "") })
    }
    function openWizard(step) {
        wizardStep = step
        page = "Setup"
    }
    function primaryAction() {
        if (launcher.setupRunning) return
        if (gameBlocked) { openWizard(1); return }
        if (savesBlocked) { openWizard(2); return }
        if (onlineBlocked) {
            const target = launcher.playModeSettings
            openSettingsPage(launcher.pageFor(target[0], target[1]), target[0], target[1], "")
            return
        }
        if (!launcher.running) launcher.playSelected()
    }

    Component.onCompleted: {
        wizardStep = launcher.wizardStartStep
        if (launcher.startPage === "Setup") page = "Setup"
        else if (launcher.startPage === "Log") page = "Logs"
        else if (launcher.startPage === "Game") page = "Game"
        else page = "Home"
        launcher.debugPage("completed page=" + page + " size=" + width + "x" + height +
                           " start=" + launcher.startPage)
    }

    Shortcut { sequence: "Ctrl+1"; onActivated: window.openPage("Home") }
    Shortcut { sequence: "Ctrl+2"; onActivated: window.openPage("Graphics") }
    Shortcut { sequence: "Ctrl+3"; onActivated: window.openPage("Display") }
    Shortcut { sequence: "Ctrl+4"; onActivated: window.openPage("Game") }
    Shortcut { sequence: "Ctrl+5"; onActivated: window.openPage("Mods") }
    Shortcut { sequence: "Ctrl+6"; onActivated: window.openPage("Online") }
    Shortcut { sequence: "Ctrl+7"; onActivated: window.openPage("System") }
    Shortcut { sequence: "Ctrl+L"; onActivated: window.openPage("Logs") }
    Shortcut { sequence: "Ctrl+F"; onActivated: { if (window.settingsPage) search.forceActiveFocus() } }

    Rail {
        id: rail
        height: parent.height
        current: window.page
        locked: window.page === "Setup"
        onNavigate: (target) => window.openPage(target)
    }

    Item {
        x: Theme.railWidth; width: parent.width - Theme.railWidth; height: parent.height

        // Top bar: page identity, search, live process state, compact launch action.
        Rectangle {
            id: topBar
            width: parent.width; height: Theme.topBarHeight
            color: Theme.base
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }

            Column {
                x: 28; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                Text {
                    text: window.pageTitle(); color: Theme.text; font.family: Theme.sans
                    font.pixelSize: 17; font.weight: Font.DemiBold
                }
                Text {
                    text: window.pageSubtitle(); color: Theme.textDim; font.family: Theme.sans
                    font.pixelSize: 11
                }
            }

            Row {
                anchors.right: parent.right; anchors.rightMargin: 24; anchors.verticalCenter: parent.verticalCenter
                spacing: 10
                GlassTextField {
                    id: search
                    visible: window.settingsPage
                    width: 210; height: 30
                    placeholderText: "Search settings"
                    text: window.searchQuery
                    onTextChanged: window.searchQuery = text
                }
                Rectangle {
                    height: 26; radius: 13; width: Math.max(64, stateRow.width + 18)
                    color: Theme.surface; border.color: Theme.line; border.width: 1
                    Row {
                        id: stateRow; anchors.centerIn: parent; spacing: 7
                        Rectangle {
                            width: 7; height: 7; radius: 3.5; anchors.verticalCenter: parent.verticalCenter
                            color: window.stateColor()
                        }
                        Text {
                            text: window.stateText(); color: Theme.textDim
                            font.family: Theme.sans; font.pixelSize: 11
                        }
                    }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: window.openPage("Logs")
                    }
                }
                GlassButton {
                    visible: window.page !== "Setup"
                    width: 70; height: 30
                    highlighted: !launcher.running
                    text: launcher.running ? "Stop" : "Play"
                    enabled: launcher.running || (!launcher.setupRunning
                              && launcher.launchState !== "preparing"
                              && launcher.launchState !== "starting")
                    onClicked: launcher.running ? launcher.stop() : window.primaryAction()
                }
            }
        }

        // Page content. Page changes are state changes, never animated dependencies.
        Item {
            y: Theme.topBarHeight
            width: parent.width; height: parent.height - Theme.topBarHeight - Theme.footerHeight

            HomePage {
                anchors.fill: parent
                visible: window.page === "Home"
                gameBlocked: window.gameBlocked
                savesBlocked: window.savesBlocked
                onlineBlocked: window.onlineBlocked
                onPrimaryRequested: window.primaryAction()
                onOpenPage: (target) => window.openPage(target)
            }

            SettingsWorkspace {
                id: settings
                anchors.fill: parent
                visible: window.settingsPage
                pageKey: window.page
                query: window.searchQuery
                onOpenPage: (pageName, category, section, key) =>
                            window.openSettingsPage(pageName, category, section, key)
                onOpenSetup: (step) => window.openWizard(step)
            }

            DiagnosticsPage {
                anchors.fill: parent
                visible: window.page === "Logs"
            }

            Item {
                anchors.fill: parent
                visible: window.page === "Setup"
                Rectangle { anchors.fill: parent; color: Theme.base }
                SetupWizard {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 20
                    width: Math.min(880, parent.width - 56)
                    height: parent.height - 40
                    startStep: window.wizardStep
                    onExitRequested: (target) => window.openPage(target)
                }
            }
        }

        // Persistent status line: the last action and the launch outcome remain visible.
        Rectangle {
            y: parent.height - Theme.footerHeight
            width: parent.width; height: Theme.footerHeight
            color: Theme.panel
            Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.line }
            Row {
                x: 28; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                Rectangle {
                    width: 6; height: 6; radius: 3
                    color: window.blocked ? Theme.warn : window.stateColor()
                }
                Text {
                    text: {
                        let base = launcher.notice !== "" ? launcher.notice : "Settings save automatically."
                        if (launcher.launchState === "failed" && launcher.lastExitCode !== -1)
                            base += " · exit " + launcher.lastExitCode
                        return base
                    }
                    color: launcher.launchState === "failed" ? Theme.accent
                           : window.blocked ? Theme.warn : Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 11
                    elide: Text.ElideRight; width: Math.max(200, window.width - Theme.railWidth - 70)
                }
            }
        }
    }

    font.family: Theme.sans
    palette.windowText: Theme.text
    palette.buttonText: Theme.text
    palette.text: Theme.text
    palette.highlightedText: Theme.text
}
