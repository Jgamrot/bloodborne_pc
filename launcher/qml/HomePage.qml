import QtQuick
import QtQuick.Controls

// Play: what state the game is in, one primary action, and the four things a player changes
// most, each showing its current value. Everything else lives in Settings.
Item {
    id: home
    signal primaryRequested()
    signal openSettings(string category, string section)

    property bool gameBlocked: false
    property bool savesBlocked: false
    property bool onlineBlocked: false
    property bool blocked: gameBlocked || savesBlocked || onlineBlocked || launcher.setupRunning
    property string statusTitle: launcher.running ? "The hunt is underway" :
                                 launcher.setupRunning ? "Preparing game files" :
                                 gameBlocked ? "Game files needed" :
                                 savesBlocked ? "Saves need attention" :
                                 onlineBlocked ? (launcher.playMode === "coop" ? "Co-op needs setting up" : "Sign in to play online") : "Ready to hunt"
    property string statusDetail: gameBlocked ? "Choose your Bloodborne folder, or install it from your own ZIP or PKG dump." :
                                  savesBlocked ? "The saves folder cannot be written. Choose another one." :
                                  onlineBlocked ? launcher.playModeSummary : ""
    property int enabledMods: {
        let n = 0
        for (const m of launcher.contentMods) if (m.enabled) n++
        return n
    }
    property real panelWidth: Math.max(500, Math.min(620, (width - Theme.railWidth) * 0.46))

    Rectangle { anchors.fill: parent; color: Theme.base }
    Image {
        x: Theme.railWidth + panelWidth * 0.55; y: 0
        width: parent.width - x; height: parent.height
        source: Qt.resolvedUrl("../assets/ui/launcher-bridge.png")
        fillMode: Image.PreserveAspectCrop; horizontalAlignment: Image.AlignLeft
        smooth: true; asynchronous: true
    }
    // The panel melts into the art instead of ending at a hard edge.
    Rectangle {
        x: Theme.railWidth; width: panelWidth + 220; height: parent.height
        gradient: Gradient { orientation: Gradient.Horizontal
            GradientStop { position: 0; color: "#f20b0d10" }
            GradientStop { position: panelWidth / (panelWidth + 220); color: "#f00b0d10" }
            GradientStop { position: 1; color: "#000b0d10" }
        }
    }
    Rectangle {
        anchors.bottom: parent.bottom; width: parent.width; height: 160
        gradient: Gradient { GradientStop { position: 0; color: "#000b0d10" } GradientStop { position: 1; color: "#a00b0d10" } }
    }

    Flickable {
        id: flick
        x: Theme.railWidth; width: panelWidth; height: parent.height
        clip: true; boundsBehavior: Flickable.StopAtBounds
        contentHeight: Math.max(height, column.implicitHeight + 120)
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
            id: column
            x: 44; y: 34; width: parent.width - 88
            spacing: 0

            // Breadcrumb and status.
            Item {
                width: parent.width; height: 40
                Row {
                    anchors.verticalCenter: parent.verticalCenter; spacing: 14
                    Text { text: "BLOODBORNE"; color: Theme.text; font.family: Theme.serif; font.pixelSize: 17; font.letterSpacing: 2.4 }
                    Text { text: "/"; color: Theme.textFaint; font.family: Theme.sans; font.pixelSize: 15 }
                    Text { text: "LAUNCHER"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 13; font.letterSpacing: 2 }
                }
                Row {
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    Rectangle {
                        width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter
                        color: launcher.running ? Theme.accent : home.blocked ? Theme.warn : Theme.good
                    }
                    Text {
                        text: launcher.running ? "Running" : home.blocked ? "Needs attention" : "Ready"
                        color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 13
                    }
                }
            }
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            Item { width: 1; height: 30 }
            Text {
                width: parent.width; text: home.statusTitle; color: Theme.text; wrapMode: Text.WordWrap
                font.family: Theme.serif; font.pixelSize: 46
            }
            Item { width: 1; height: 18 }
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            Item { width: 1; height: 18 }
            Text {
                width: parent.width; elide: Text.ElideRight; color: Theme.text
                font.family: Theme.serif; font.pixelSize: 18
                text: launcher.setupFacts.resolution + "  ·  " + launcher.setupFacts.frameRate + "  ·  " +
                      launcher.setupFacts.upscaler + "  ·  " + launcher.setupFacts.display
            }
            Item { width: 1; height: 6 }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
                text: home.statusDetail !== "" ? home.statusDetail : launcher.gameStatus
                color: home.blocked ? Theme.warn : Theme.textDim; font.family: Theme.sans; font.pixelSize: 13
            }
            Item { width: 1; height: 26 }

            Row {
                width: parent.width; spacing: 12
                GlassButton {
                    width: launcher.running ? parent.width - 132 : parent.width; height: 58
                    highlighted: true; serif: true
                    text: launcher.running ? "Game running" : launcher.setupRunning ? "Installing…" :
                          home.gameBlocked ? "Set up game files" : home.savesBlocked ? "Choose a saves folder" :
                          home.onlineBlocked ? (launcher.playMode === "coop" ? "Set up co-op" : "Sign in with Discord") :
                          launcher.playMode === "coop" ? "Play co-op" : launcher.playMode === "huntersdream" && !launcher.thdRefused ? "Play online" : "Play offline"
                    enabled: !launcher.running && !launcher.setupRunning
                    onClicked: home.primaryRequested()
                }
                GlassButton {
                    visible: launcher.running; width: 120; height: 58; text: "Stop"
                    onClicked: launcher.stop()
                }
            }
            Item { width: 1; height: 12 }

            // How PLAY starts the game: offline, online on The Hunter's Dream, or seamless co-op.
            Row {
                id: modes
                width: parent.width; spacing: 8
                Repeater {
                    model: [{mode: "offline", label: "Offline"},
                            {mode: "huntersdream", label: "Online · The Hunter's Dream"},
                            {mode: "coop", label: "Online · Seamless co-op"}]
                    delegate: Rectangle {
                        readonly property bool chosen: launcher.playMode === modelData.mode
                        width: (modes.width - modes.spacing * 2) / 3; height: 40; radius: Theme.radius
                        color: chosen ? Theme.surfaceHover : modeArea.containsMouse ? Theme.surfaceHover : "transparent"
                        border.width: 1; border.color: chosen ? Theme.accent : modeArea.containsMouse ? Theme.lineStrong : Theme.line
                        Text {
                            anchors.fill: parent; anchors.margins: 6
                            text: modelData.label; elide: Text.ElideRight
                            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
                            color: parent.chosen ? Theme.text : Theme.textDim
                            font.family: Theme.sans; font.pixelSize: 13
                        }
                        MouseArea {
                            id: modeArea; anchors.fill: parent; hoverEnabled: true
                            enabled: !launcher.running
                            cursorShape: Qt.PointingHandCursor
                            onClicked: launcher.setPlayMode(modelData.mode)
                        }
                    }
                }
            }
            Item { width: 1; height: 8 }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: launcher.playModeSummary
                color: home.onlineBlocked ? Theme.warn : Theme.textDim
                font.family: Theme.sans; font.pixelSize: 13
            }
            Item { width: 1; height: 22 }

            MenuRow {
                visible: launcher.portIncomplete
                width: parent.width; icon: "update"; selected: true
                label: "Some port files are missing"; value: launcher.repairing ? "Repairing…" : "Repair"; valueColor: Theme.text
                onClicked: launcher.repairPort()
            }
            Item { visible: launcher.portIncomplete; width: 1; height: 12 }

            MenuRow {
                visible: launcher.hasUpdate
                width: parent.width; icon: "update"; selected: true
                label: "A new version is ready"; value: "Install"; valueColor: Theme.text
                onClicked: launcher.installUpdate()
            }
            Item { visible: launcher.hasUpdate; width: 1; height: 12 }

            Column {
                width: parent.width; spacing: 12
                MenuRow {
                    width: parent.width; icon: "visuals"; label: "Graphics"
                    value: launcher.graphicsPreset === "custom" ? "Custom" : launcher.presetLabel(launcher.graphicsPreset) + " preset"
                    onClicked: home.openSettings("Visuals", "")
                }
                MenuRow {
                    width: parent.width; icon: "controls"; label: "Controls"
                    value: launcher.promptChoice + " prompts"
                    onClicked: home.openSettings("Controls", "Button prompts")
                }
                MenuRow {
                    width: parent.width; icon: "folder"; label: "Game files & saves"
                    value: home.gameBlocked || home.savesBlocked ? "Needs attention" : "Ready"
                    valueColor: home.gameBlocked || home.savesBlocked ? Theme.warn : Theme.textDim
                    onClicked: home.openSettings("Game & Saves", home.savesBlocked && !home.gameBlocked ? "Your data" : "Game files")
                }
                MenuRow {
                    width: parent.width; icon: "puzzle"; label: "Mods & patches"
                    value: home.enabledMods === 0 ? "None enabled" : home.enabledMods + (home.enabledMods === 1 ? " mod enabled" : " mods enabled")
                    onClicked: home.openSettings("Mods & Patches", "Installed mods")
                }
            }
        }

        // Hints sit at the foot of the panel, as the guide's key help does.
        Column {
            x: 44; width: parent.width - 88
            y: Math.max(column.y + column.implicitHeight + 28, flick.contentHeight - implicitHeight - 26)
            spacing: 10
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; color: Theme.textDim
                font.family: Theme.sans; font.pixelSize: 12; lineHeight: 1.35
                text: launcher.notice !== "Ready to hunt." && launcher.notice !== "" ? launcher.notice :
                      "Hold Shift while starting to open this launcher  ·  Insert or L3+R3 opens the guide in game"
            }
        }
    }
}
