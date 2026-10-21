import QtQuick
import QtQuick.Controls

// Overview: launch state, readiness, current configuration and quick destinations.
Item {
    id: home
    signal primaryRequested()
    signal openPage(string page)

    property bool gameBlocked: false
    property bool savesBlocked: false
    property bool onlineBlocked: false
    property bool blocked: gameBlocked || savesBlocked || onlineBlocked || launcher.setupRunning
    property int enabledMods: {
        let count = 0
        for (const mod of launcher.contentMods) if (mod.enabled) count++
        return count
    }
    property string stateTitle: {
        if (launcher.launchState === "preparing") return "Preparing game files"
        if (launcher.launchState === "starting") return "Starting Bloodborne"
        if (launcher.launchState === "running") return "Bloodborne is running"
        if (launcher.launchState === "failed") return "The last launch failed"
        if (home.gameBlocked) return "Game files required"
        if (home.savesBlocked) return "Saves folder required"
        if (home.onlineBlocked) return launcher.playMode === "coop" ? "Co-op needs setup" : "Sign-in required"
        return "Ready to hunt"
    }
    property string stateDetail: {
        if (launcher.launchState === "failed") return launcher.notice
        if (launcher.launchState === "starting" || launcher.launchState === "preparing")
            return "The launcher is preparing the game. This can take a few seconds."
        if (launcher.launchState === "running")
            return "The launcher is idle. Settings changed now apply at the next start."
        if (home.gameBlocked) return "Choose your own Bloodborne 1.09 folder, or install it from a ZIP or PKG dump."
        if (home.savesBlocked) return "The saves folder cannot be written. Choose another one."
        if (home.onlineBlocked) return launcher.playModeSummary
        return launcher.gameStatus + ". " + launcher.playModeSummary
    }
    property string primaryText: {
        if (launcher.running) return "Stop game"
        if (launcher.setupRunning) return "Installing game files…"
        if (home.gameBlocked) return "Set up game files"
        if (home.savesBlocked) return "Choose a saves folder"
        if (home.onlineBlocked) return launcher.playMode === "coop" ? "Set up co-op" : "Sign in with Discord"
        return launcher.playMode === "coop" ? "Play co-op" :
               launcher.playMode === "huntersdream" ? "Play online" : "Play offline"
    }
    property color stateAccent: launcher.launchState === "failed" ? Theme.accent :
                                launcher.running ? Theme.good :
                                home.blocked ? Theme.warn : Theme.good

    Rectangle { anchors.fill: parent; color: Theme.base }

    Flickable {
        id: scroll
        anchors.fill: parent
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: content.implicitHeight + 56
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
            id: content
            x: 28; y: 22
            width: Math.min(Theme.pageMaxWidth, home.width - 56)
            spacing: 0

            // Identity and state.
            Row {
                width: parent.width; height: 48; spacing: 13
                Image {
                    width: 38; height: 38; anchors.verticalCenter: parent.verticalCenter
                    source: Qt.resolvedUrl("../assets/hunter-icon.png")
                    fillMode: Image.PreserveAspectCrop; smooth: true; mipmap: true
                }
                Column {
                    anchors.verticalCenter: parent.verticalCenter; spacing: 2
                    Text {
                        text: "BLOODBORNE"; color: Theme.text; font.family: Theme.serif
                        font.pixelSize: 20; font.letterSpacing: 2.2
                    }
                    Text {
                        text: "WINDOWS PORT  ·  v" + launcher.version; color: Theme.textDim
                        font.family: Theme.sans; font.pixelSize: 11; font.letterSpacing: 0.8
                    }
                }
                Item { width: Math.max(0, parent.width - 38 - 13 - homeState.width - 20); height: 1 }
                Rectangle {
                    id: homeState
                    width: Math.max(64, stateLabel.width + 26); height: 26; radius: 13
                    color: Theme.surface; border.color: Theme.line; border.width: 1
                    Row {
                        id: stateLabel; anchors.centerIn: parent; spacing: 7
                        Rectangle { width: 7; height: 7; radius: 3.5; anchors.verticalCenter: parent.verticalCenter; color: home.stateAccent }
                        Text {
                            text: launcher.launchState === "running" ? "Running" :
                                  launcher.launchState === "starting" ? "Starting" :
                                  launcher.launchState === "preparing" ? "Preparing" :
                                  launcher.launchState === "failed" ? "Failed" : "Ready"
                            color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11
                        }
                    }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: home.openPage("Logs") }
                }
            }
            Item { width: 1; height: 16 }
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            Item { width: 1; height: 20 }

            Row {
                id: mainRow
                width: parent.width
                spacing: 32

                // Launch and readiness.
                Column {
                    width: Math.max(470, mainRow.width * 0.61)
                    spacing: 0

                    Text {
                        text: "LAUNCH"; color: Theme.textFaint; font.family: Theme.sans
                        font.pixelSize: 10; font.letterSpacing: 1.4
                    }
                    Item { width: 1; height: 8 }
                    Text {
                        width: parent.width; text: home.stateTitle; color: Theme.text
                        font.family: Theme.sans; font.pixelSize: 25; font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                    }
                    Item { width: 1; height: 6 }
                    Text {
                        width: parent.width; text: home.stateDetail; color: Theme.textDim
                        font.family: Theme.sans; font.pixelSize: 12; wrapMode: Text.WordWrap
                        lineHeight: 1.35
                    }
                    Row {
                        visible: launcher.launchState === "preparing" || launcher.launchState === "starting"
                        spacing: 8
                        BusyIndicator { width: 18; height: 18; running: parent.visible }
                        Text {
                            text: launcher.launchState === "preparing" ? "Preparing game files" : "Starting the game"
                            color: Theme.warn; font.family: Theme.sans; font.pixelSize: 11
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Item { width: 1; height: 18 }

                    Text {
                        text: "LAUNCH MODE"; color: Theme.textFaint; font.family: Theme.sans
                        font.pixelSize: 10; font.letterSpacing: 1.3
                    }
                    Item { width: 1; height: 6 }
                    Row {
                        id: modes
                        width: parent.width; spacing: 8
                        Repeater {
                            model: [
                                {mode: "offline", label: "Offline", detail: "Own world"},
                                {mode: "huntersdream", label: "Online", detail: "The Hunter's Dream"},
                                {mode: "coop", label: "Co-op", detail: "Seamless session"}
                            ]
                            delegate: Rectangle {
                                id: modeTile
                                width: (modes.width - 16) / 3; height: 42; radius: Theme.radiusSmall
                                property bool chosen: launcher.playMode === modelData.mode
                                color: chosen ? Theme.surfaceActive : modeHit.containsMouse ? Theme.surfaceHover : "transparent"
                                border.width: 1; border.color: chosen ? Theme.accent : Theme.line
                                Column {
                                    anchors.centerIn: parent; spacing: 1
                                    Text {
                                        text: modelData.label; color: modeTile.chosen ? Theme.text : Theme.textDim
                                        font.family: Theme.sans; font.pixelSize: 12; font.weight: Font.DemiBold
                                    }
                                    Text {
                                        text: modelData.detail; color: Theme.textFaint
                                        font.family: Theme.sans; font.pixelSize: 9
                                    }
                                }
                                MouseArea {
                                    id: modeHit; anchors.fill: parent; hoverEnabled: true
                                    enabled: !launcher.running && !launcher.setupRunning
                                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onClicked: launcher.setPlayMode(modelData.mode)
                                }
                                Accessible.role: Accessible.RadioButton
                                Accessible.name: modelData.label
                                Accessible.checked: modeTile.chosen
                            }
                        }
                    }
                    Item { width: 1; height: 14 }

                    GlassButton {
                        width: parent.width; height: 44; highlighted: true; serif: true
                        text: home.primaryText
                        enabled: launcher.running || (!launcher.setupRunning
                                  && launcher.launchState !== "preparing"
                                  && launcher.launchState !== "starting")
                        onClicked: launcher.running ? launcher.stop() : home.primaryRequested()
                    }
                    Item { width: 1; height: 18 }

                    Text {
                        text: "READINESS"; color: Theme.textFaint; font.family: Theme.sans
                        font.pixelSize: 10; font.letterSpacing: 1.3
                    }
                    Item { width: 1; height: 4 }
                    Repeater {
                        model: launcher.readiness
                        delegate: Item {
                            width: parent.width; height: 28
                            Row {
                                anchors.verticalCenter: parent.verticalCenter; spacing: 8
                                Rectangle {
                                    width: 7; height: 7; radius: 3.5
                                    color: modelData.level === "error" ? Theme.accent :
                                           modelData.level === "warning" ? Theme.warn : Theme.good
                                }
                                Text {
                                    text: modelData.label; color: Theme.text
                                    font.family: Theme.sans; font.pixelSize: 12
                                }
                                Text {
                                    text: modelData.detail || ""; color: Theme.textDim
                                    font.family: Theme.sans; font.pixelSize: 11
                                    elide: Text.ElideRight; width: parent.width - 170
                                }
                            }
                            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                        }
                    }
                    Text {
                        visible: launcher.readiness.length === 0
                        text: "Checking game files…"; color: Theme.textDim
                        font.family: Theme.sans; font.pixelSize: 11
                    }
                    Item { width: 1; height: 14 }

                    Rectangle {
                        visible: launcher.hasUpdate
                        width: parent.width; height: 34
                        color: Theme.accentSoft
                        Rectangle { width: 2; height: parent.height; color: Theme.accent }
                        Row {
                            anchors.left: parent.left; anchors.leftMargin: 12; anchors.verticalCenter: parent.verticalCenter
                            spacing: 10
                            Text {
                                text: "Update available" + (launcher.updateVersion ? " · v" + launcher.updateVersion : "")
                                color: Theme.text; font.family: Theme.sans; font.pixelSize: 12
                            }
                            GlassButton { text: "Install"; width: 70; height: 24; highlighted: true; onClicked: launcher.installUpdate() }
                            GlassButton { text: "Notes"; width: 70; height: 24; onClicked: launcher.action("releases") }
                        }
                    }
                    Item { visible: launcher.hasUpdate; width: 1; height: 12 }
                }

                // Current configuration and runtime facts.
                Column {
                    width: mainRow.width - mainRow.width * 0.61 - 32
                    spacing: 0
                    Text {
                        text: "CURRENT CONFIGURATION"; color: Theme.textFaint; font.family: Theme.sans
                        font.pixelSize: 10; font.letterSpacing: 1.3
                    }
                    Item { width: 1; height: 8 }
                    Rectangle { width: parent.width; height: 1; color: Theme.line }
                    ConfigRow { label: "Output"; value: launcher.setupFacts.resolution }
                    ConfigRow { label: "Frame rate"; value: launcher.setupFacts.frameRate }
                    ConfigRow { label: "Upscaler"; value: launcher.setupFacts.upscaler }
                    ConfigRow {
                        label: "Preset"
                        value: launcher.graphicsPreset === "custom" ? "Custom" : launcher.presetLabel(launcher.graphicsPreset)
                    }
                    ConfigRow { label: "Window"; value: launcher.setupFacts.display }
                    ConfigRow { label: "Presentation"; value: String(launcher.value("present_mode")) }
                    ConfigRow { label: "GPU"; value: launcher.gpuStatus }
                    ConfigRow { label: "FSR assets"; value: launcher.fsrStatus }
                    Item { width: 1; height: 12 }
                    Row {
                        spacing: 8
                        GlassButton { text: "Graphics"; width: 100; height: 30; onClicked: home.openPage("Graphics") }
                        GlassButton { text: "Display"; width: 90; height: 30; onClicked: home.openPage("Display") }
                    }

                    Item { width: 1; height: 20 }
                    Text {
                        visible: launcher.runtimeInfo.upscaler !== "" || launcher.runtimeInfo.gpu !== ""
                        text: "LAST RUNTIME REPORT"; color: Theme.textFaint; font.family: Theme.sans
                        font.pixelSize: 10; font.letterSpacing: 1.3
                    }
                    Rectangle {
                        visible: launcher.runtimeInfo.upscaler !== "" || launcher.runtimeInfo.gpu !== ""
                        width: parent.width; height: 1; color: Theme.line
                    }
                    Text {
                        visible: launcher.runtimeInfo.upscaler !== ""
                        width: parent.width; text: launcher.runtimeInfo.upscaler; color: Theme.textDim
                        font.family: Theme.sans; font.pixelSize: 11; wrapMode: Text.WordWrap
                    }
                    Text {
                        visible: launcher.runtimeInfo.error !== ""
                        width: parent.width; text: launcher.runtimeInfo.error; color: Theme.warn
                        font.family: Theme.sans; font.pixelSize: 11; wrapMode: Text.WordWrap
                    }
                }
            }

            Item { width: 1; height: 26 }
            Text {
                text: "QUICK ACCESS"; color: Theme.textFaint; font.family: Theme.sans
                font.pixelSize: 10; font.letterSpacing: 1.3
            }
            Item { width: 1; height: 6 }
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            Grid {
                id: quick
                width: parent.width
                columns: width > 900 ? 3 : 2
                columnSpacing: 24
                Repeater {
                    model: [
                        {label: "Graphics & upscaling", value: launcher.graphicsPreset === "custom" ? "Custom preset" : launcher.presetLabel(launcher.graphicsPreset), page: "Graphics"},
                        {label: "Display & pacing", value: launcher.setupFacts.resolution + " · " + launcher.setupFacts.frameRate, page: "Display"},
                        {label: "Game files & saves", value: home.gameBlocked || home.savesBlocked ? "Needs attention" : "Ready", page: "Game"},
                        {label: "Mods & patches", value: home.enabledMods === 0 ? "None enabled" : home.enabledMods + " enabled", page: "Mods"},
                        {label: "Online & co-op", value: launcher.playModeSummary, page: "Online"},
                        {label: "Diagnostics", value: launcher.launchState === "failed" ? "Last launch failed" : "Logs and runtime", page: "Logs"}
                    ]
                    delegate: Item {
                        width: (quick.width - quick.columnSpacing * (quick.columns - 1)) / quick.columns
                        height: 50
                        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                        Column {
                            x: 2; y: 9; width: parent.width - 12; spacing: 2
                            Text { text: modelData.label; color: Theme.text; font.family: Theme.sans; font.pixelSize: 12 }
                            Text {
                                width: parent.width; text: modelData.value; color: Theme.textDim
                                font.family: Theme.sans; font.pixelSize: 11; elide: Text.ElideRight
                            }
                        }
                        MouseArea { id: quickHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: home.openPage(modelData.page) }
                        Rectangle {
                            visible: quickHit.containsMouse
                            width: 2; height: parent.height - 14; anchors.verticalCenter: parent.verticalCenter
                            color: Theme.accent
                        }
                    }
                }
            }

            Item { width: 1; height: 18 }
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            Item { width: 1; height: 8 }
            Text {
                width: parent.width; wrapMode: Text.WordWrap; color: Theme.textFaint
                font.family: Theme.sans; font.pixelSize: 11; lineHeight: 1.35
                text: "Insert or L3+R3 opens the in-game menu. Hold Shift while starting to open this launcher. " +
                      "Settings save as you change them; restart the game to apply startup options."
            }
        }
    }

    component ConfigRow: Item {
        property string label: ""
        property string value: ""
        width: parent ? parent.width : 0
        height: 28
        Text {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            text: parent.label; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11
        }
        Text {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth, parent.width * 0.58)
            text: parent.value; color: Theme.text; font.family: Theme.sans; font.pixelSize: 12
            horizontalAlignment: Text.AlignRight; elide: Text.ElideRight
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
    }
}
