import QtQuick
import QtQuick.Controls

// First-time setup: four clear steps on one panel. No decorative art or gradients.
Item {
    id: wizard
    objectName: "setupWizard"
    property int step: 0
    property int startStep: 0
    property var checks: launcher.readiness
    property bool gameValid: checks.length > 0 && checks[0].level !== "error"
    property bool savesValid: checks.length > 2 && checks[2].level !== "error" && launcher.savesWritable
    signal exitRequested(string page)
    onVisibleChanged: {
        if (visible) step = startStep
        launcher.debugPage("wizard visible=" + visible + " step=" + step)
    }
    onStepChanged: launcher.debugPage("wizard step=" + step)

    function levelColor(level) {
        return level === "ready" ? Theme.good : level === "error" ? Theme.accent : Theme.warn
    }
    function dataLevel() {
        const levels = checks.slice(1).map(function(c) { return c.level })
        return levels.indexOf("error") >= 0 ? "error" :
               levels.every(function(l) { return l === "ready" }) ? "ready" : "warning"
    }
    function stepValid(index) { return index === 1 ? gameValid : index === 2 ? savesValid : true }
    function canReach(index) {
        for (let i = 0; i < index; i++) if (!stepValid(i)) return false
        return true
    }
    function skip() {
        if (!launcher.confirm("Skip setup?",
                "Missing game files or an unwritable saves folder will still block Play. You can finish setup later in Game & saves.\n\nSkip setup anyway?"))
            return
        launcher.skipSetup()
        wizard.exitRequested("Home")
    }
    function finish(play) {
        if (!gameValid || !savesValid) {
            launcher.skipSetup()
            wizard.exitRequested("Home")
            return
        }
        launcher.completeSetup()
        wizard.exitRequested("Home")
        if (play) launcher.play()
    }

    Rectangle { anchors.fill: parent; color: Theme.base }

    Column {
        id: header
        x: 0; y: 0; width: parent.width; spacing: 0
        Row {
            width: parent.width; height: 40; spacing: 11
            Image {
                width: 28; height: 28; anchors.verticalCenter: parent.verticalCenter
                source: Qt.resolvedUrl("../assets/hunter-icon.png")
                fillMode: Image.PreserveAspectCrop; smooth: true; mipmap: true
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter; spacing: 1
                Text {
                    text: "BLOODBORNE"; color: Theme.text; font.family: Theme.serif
                    font.pixelSize: 14; font.letterSpacing: 1.8
                }
                Text {
                    text: "FIRST-TIME SETUP"; color: Theme.textFaint; font.family: Theme.sans
                    font.pixelSize: 10; font.letterSpacing: 1.3
                }
            }
            Item { width: Math.max(40, parent.width - 28 - 11 - 170); height: 1 }
            Text {
                text: "Step " + (wizard.step + 1) + " of 4"; color: Theme.textDim
                font.family: Theme.sans; font.pixelSize: 11
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        Item { width: 1; height: 6 }
        Rectangle { width: parent.width; height: 1; color: Theme.line }
        Item { width: 1; height: 12 }

        Row {
            width: parent.width; spacing: 0
            Repeater {
                model: ["Welcome", "Game files", "Your data", "Finish"]
                delegate: Item {
                    id: stepTab
                    width: header.width / 4; height: 28
                    property bool current: index === wizard.step
                    property bool done: index < wizard.step
                    property bool reachable: index <= wizard.step || wizard.canReach(index)
                    Rectangle {
                        x: 0; y: 5; width: parent.width - 10; height: 2
                        color: stepTab.done || stepTab.current ? Theme.accent : Theme.line
                    }
                    Rectangle {
                        x: 0; y: 1; width: 10; height: 10; radius: 5
                        color: stepTab.current ? Theme.accent : stepTab.done ? Theme.good : Theme.lineStrong
                    }
                    Text {
                        x: 16; y: 0; text: (index + 1) + "  " + modelData
                        color: stepTab.current ? Theme.text : stepTab.reachable ? Theme.textDim : Theme.textFaint
                        font.family: Theme.sans; font.pixelSize: 11
                    }
                }
            }
        }
    }

    Rectangle {
        id: footer
        anchors.bottom: parent.bottom
        width: parent.width; height: 44
        color: Theme.base
        Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.line }
        Row {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            GlassButton { visible: wizard.step === 0; text: "Start setup"; width: 124; height: 30; highlighted: true; onClicked: wizard.step = 1 }
            GlassButton { visible: wizard.step === 0; text: "Skip for now"; width: 132; height: 30; onClicked: { launcher.skipSetup(); wizard.exitRequested("Home") } }
            GlassButton { visible: wizard.step > 0; text: "Back"; width: 70; height: 30; onClicked: wizard.step-- }
            GlassButton {
                visible: wizard.step === 1 || wizard.step === 2
                text: "Continue"; width: 100; height: 30; highlighted: true
                enabled: wizard.stepValid(wizard.step)
                onClicked: wizard.step++
            }
            GlassButton {
                visible: wizard.step === 3; text: "Play"; width: 88; height: 30; highlighted: true
                enabled: wizard.gameValid && wizard.savesValid && !launcher.running && !launcher.setupRunning
                onClicked: wizard.finish(true)
            }
            GlassButton { visible: wizard.step === 3; text: "Open launcher"; width: 118; height: 30; onClicked: wizard.finish(false) }
        }
        Row {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            spacing: 10
            Text {
                visible: wizard.step === 1 && !wizard.gameValid
                anchors.verticalCenter: parent.verticalCenter
                text: "Add valid game files to continue."; color: Theme.textDim
                font.family: Theme.sans; font.pixelSize: 10
            }
            GlassButton { visible: wizard.step === 1 || wizard.step === 2; text: "Skip setup"; width: 94; height: 30; onClicked: wizard.skip() }
        }
    }

    Flickable {
        id: body
        anchors.top: header.bottom
        anchors.bottom: footer.top
        width: parent.width
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: stepColumn.implicitHeight + 20
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
            id: stepColumn
            width: body.width
            spacing: 0

            Column {
                visible: wizard.step === 0
                width: parent.width; spacing: 12
                Text {
                    width: parent.width; text: "Welcome to Yharnam"
                    color: Theme.text; font.family: Theme.sans
                    font.pixelSize: 24; font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap; color: Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 12; lineHeight: 1.4
                    text: "This wizard sets up your own copy of Bloodborne, checks the game files, saves and optional trophy key, and prepares the first launch. It takes about two minutes."
                }
                Rectangle { width: parent.width; height: 1; color: Theme.line }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap; color: Theme.text
                    font.family: Theme.sans; font.pixelSize: 12; lineHeight: 1.45
                    text: "You need your own decrypted CUSA03173 game dump (version 1.09 for the community patches). The game files and trophy key are not included in this download. Already have a folder with eboot.bin? Choose it on the next step."
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap; color: Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 11; lineHeight: 1.35
                    text: "You can skip setup and configure everything later from Game & saves and System."
                }
            }

            Column {
                visible: wizard.step === 1
                width: parent.width; spacing: 12
                Text {
                    width: parent.width; text: "Add your game files"
                    color: Theme.text; font.family: Theme.sans
                    font.pixelSize: 24; font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap; color: Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 12; lineHeight: 1.4
                    text: "The installer creates a new game folder and never replaces an existing one. For cusa-03173.zip, choose the ZIP and then the destination, such as C:\\Games\\Bloodborne. For an extracted game, choose the folder that contains eboot.bin."
                }
                Flow {
                    width: parent.width; spacing: 8
                    GlassButton {
                        text: launcher.setupRunning ? "Installing…" : "Install from ZIP / PKG"
                        width: 190; height: 32; highlighted: true
                        enabled: !launcher.setupRunning && !launcher.running
                        onClicked: launcher.installFromArchive()
                    }
                    GlassButton { text: "Choose a game folder"; height: 32; enabled: !launcher.setupRunning; onClicked: launcher.browse("game_dir") }
                }
                Rectangle { width: parent.width; height: 1; color: Theme.line }
                Repeater {
                    model: wizard.checks.length > 0 ? wizard.checks.slice(0, 1) : []
                    delegate: Row {
                        width: stepColumn.width; spacing: 8
                        Rectangle { width: 7; height: 7; radius: 3.5; y: 5; color: wizard.levelColor(modelData.level) }
                        Text {
                            width: stepColumn.width - 24
                            text: modelData.label + ":  " + modelData.detail
                            color: Theme.text; font.family: Theme.sans; font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }
                }
                GlassButton { text: "Check again"; height: 30; onClicked: launcher.refreshReadiness() }
            }

            Column {
                visible: wizard.step === 2
                width: parent.width; spacing: 12
                Text {
                    width: parent.width; text: "Your data"
                    color: Theme.text; font.family: Theme.sans
                    font.pixelSize: 24; font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap; color: Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 12; lineHeight: 1.4
                    text: "A writable saves folder is required. Trophy keys are optional and add trophy names. Saves stay in the launcher's own user folder unless you choose another one."
                }
                Flow {
                    width: parent.width; spacing: 8
                    GlassButton { text: "Import trophy keys"; height: 32; onClicked: launcher.importTrophyKeys() }
                    GlassButton { text: "Choose a saves folder"; height: 32; onClicked: launcher.browse("user_dir") }
                }
                Rectangle { width: parent.width; height: 1; color: Theme.line }
                Repeater {
                    model: wizard.checks.slice(1)
                    delegate: Row {
                        width: stepColumn.width; spacing: 8
                        Rectangle { width: 7; height: 7; radius: 3.5; y: 5; color: wizard.levelColor(modelData.level) }
                        Text {
                            width: stepColumn.width - 24
                            text: modelData.label + ":  " + modelData.detail
                            color: Theme.text; font.family: Theme.sans; font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }
                }
                GlassButton { text: "Check again"; height: 30; onClicked: launcher.refreshReadiness() }
            }

            Column {
                visible: wizard.step === 3
                width: parent.width; spacing: 12
                Text {
                    width: parent.width; text: "Ready to hunt"
                    color: Theme.text; font.family: Theme.sans
                    font.pixelSize: 24; font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    color: wizard.gameValid && wizard.savesValid ? Theme.textDim : Theme.warn
                    font.family: Theme.sans; font.pixelSize: 12; lineHeight: 1.4
                    text: wizard.gameValid && wizard.savesValid
                          ? "Your game files and saves are ready. Pick a graphics preset, then start playing or open the launcher."
                          : "A required check needs attention. Go back to Game files or Your data to fix it."
                }
                Repeater {
                    model: wizard.checks
                    delegate: Row {
                        width: stepColumn.width; spacing: 8
                        Rectangle { width: 7; height: 7; radius: 3.5; y: 5; color: wizard.levelColor(modelData.level) }
                        Text {
                            width: stepColumn.width - 24
                            text: modelData.label + ":  " + modelData.detail
                            color: Theme.text; font.family: Theme.sans; font.pixelSize: 12
                            wrapMode: Text.WordWrap
                        }
                    }
                }
                Rectangle { width: parent.width; height: 1; color: Theme.line }
                Text { text: "GRAPHICS"; color: Theme.textFaint; font.family: Theme.sans; font.pixelSize: 10; font.letterSpacing: 1.3 }
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: ["low", "balanced", "high", "ultra"]
                        delegate: GlassButton {
                            width: 96; height: 30
                            text: launcher.presetLabel(modelData) + (launcher.recommendedPreset === modelData ? "  *" : "")
                            highlighted: launcher.graphicsPreset === modelData
                            onClicked: launcher.applyGraphicsPreset(modelData)
                        }
                    }
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap; color: Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 11; lineHeight: 1.3
                    text: launcher.presetDescription(launcher.graphicsPreset) +
                          (launcher.recommendedPreset !== "" ? "  * Suggested for the detected card." : "")
                }
                Rectangle { width: parent.width; height: 1; color: Theme.line }
                GlassSwitch {
                    text: "Start the game directly next time"
                    checked: launcher.launchDirectly
                    onToggled: launcher.setValue("launchDirectly", checked)
                }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap; color: Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 11; lineHeight: 1.35
                    text: "Hold Shift while starting to open the launcher instead. In the game, Insert or L3+R3 opens the guide. Setup can be reopened from Game & saves."
                }
            }
        }
    }
}
