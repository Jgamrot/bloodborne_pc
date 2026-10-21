import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Diagnostics: process state, runtime facts, paths and the live session log.
Item {
    id: diagnostics
    Rectangle { anchors.fill: parent; color: Theme.base }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 28
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Text {
                text: "SESSION"; color: Theme.textFaint; font.family: Theme.sans
                font.pixelSize: 10; font.letterSpacing: 1.3
            }
            Rectangle {
                width: 7; height: 7; radius: 3.5
                color: launcher.launchState === "failed" ? Theme.accent :
                       launcher.launchState === "running" ? Theme.good :
                       launcher.launchState === "starting" ? Theme.warn : Theme.textFaint
            }
            Text {
                text: launcher.launchState; color: Theme.text
                font.family: Theme.sans; font.pixelSize: 12
            }
            Item { Layout.fillWidth: true }
            Text {
                text: "Last exit: " + (launcher.lastExitCode === -1 ? "—" : launcher.lastExitCode)
                color: launcher.launchState === "failed" ? Theme.accent : Theme.textDim
                font.family: Theme.sans; font.pixelSize: 11
            }
            Text {
                text: launcher.logStats.lines + " lines · " + launcher.logStats.errors + " errors · " +
                      launcher.logStats.warnings + " warnings"
                color: Theme.textFaint; font.family: Theme.sans; font.pixelSize: 10
            }
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }

        GridLayout {
            Layout.fillWidth: true
            columns: diagnostics.width > 1150 ? 4 : 2
            columnSpacing: 28
            rowSpacing: 2
            Text { text: "GPU"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11 }
            Text {
                Layout.fillWidth: true; Layout.columnSpan: diagnostics.width > 1150 ? 1 : 1
                text: launcher.runtimeInfo.gpu || launcher.gpuStatus || "Not reported"
                color: Theme.text; font.family: Theme.sans; font.pixelSize: 11
                elide: Text.ElideRight
            }
            Text { text: "Active upscaler"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11 }
            Text {
                Layout.fillWidth: true
                text: launcher.runtimeInfo.upscaler || "Not reported until the game runs"
                color: launcher.runtimeInfo.error !== "" ? Theme.warn : Theme.text
                font.family: Theme.sans; font.pixelSize: 11; elide: Text.ElideRight
            }
            Text { text: "Object motion"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11 }
            Text {
                Layout.fillWidth: true
                text: launcher.runtimeInfo.objectMotion || "Not reported"
                color: Theme.text; font.family: Theme.sans; font.pixelSize: 11; elide: Text.ElideRight
            }
            Text { text: "Presentation"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11 }
            Text {
                Layout.fillWidth: true
                text: launcher.runtimeInfo.presentMode || "Not reported"
                color: Theme.text; font.family: Theme.sans; font.pixelSize: 11; elide: Text.ElideRight
            }
            Text { text: "Output"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11 }
            Text {
                Layout.fillWidth: true
                text: launcher.runtimeInfo.output || "Not reported"
                color: Theme.text; font.family: Theme.sans; font.pixelSize: 11; elide: Text.ElideRight
            }
            Text { text: "FSR assets"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11 }
            Text {
                Layout.fillWidth: true
                text: launcher.fsrStatus; color: Theme.text
                font.family: Theme.sans; font.pixelSize: 11; elide: Text.ElideRight
            }
        }
        Text {
            visible: launcher.runtimeInfo.error !== ""
            Layout.fillWidth: true; text: launcher.runtimeInfo.error; color: Theme.warn
            font.family: Theme.sans; font.pixelSize: 11; wrapMode: Text.WordWrap
        }

        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.line }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 18
            rowSpacing: 2
            Text { text: "Port"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 10 }
            Text {
                Layout.fillWidth: true; text: launcher.paths.port; color: Theme.textFaint
                font.family: Theme.mono; font.pixelSize: 10; elide: Text.ElideMiddle
            }
            Text { text: "Config"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 10 }
            Text {
                Layout.fillWidth: true; text: launcher.paths.config; color: Theme.textFaint
                font.family: Theme.mono; font.pixelSize: 10; elide: Text.ElideMiddle
            }
            Text { text: "Saves"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 10 }
            Text {
                Layout.fillWidth: true; text: launcher.paths.saves; color: Theme.textFaint
                font.family: Theme.mono; font.pixelSize: 10; elide: Text.ElideMiddle
            }
            Text { text: "Run log"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 10 }
            Text {
                Layout.fillWidth: true; text: launcher.paths.log; color: Theme.textFaint
                font.family: Theme.mono; font.pixelSize: 10; elide: Text.ElideMiddle
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 8
            GlassButton { text: "Open port folder"; height: 28; onClicked: launcher.action("openPort") }
            GlassButton { text: "Open bbport.ini"; height: 28; onClicked: launcher.action("openConfig") }
            GlassButton { text: "Open log folder"; height: 28; onClicked: launcher.action("openLogs") }
            GlassButton { text: "Copy log"; height: 28; onClicked: launcher.action("copyLog") }
            GlassButton { text: "Save log…"; height: 28; onClicked: launcher.action("exportLog") }
            GlassButton { text: "Clear log"; height: 28; onClicked: launcher.action("clearLog") }
            GlassButton { text: "Clear shader cache"; height: 28; onClicked: launcher.action("clearCache") }
            GlassSwitch {
                id: follow
                text: "Follow output"
                checked: true
                Accessible.name: "Follow output"
                onToggled: { if (checked) logView.positionViewAtEnd() }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.panel
            border.color: Theme.line
            border.width: 1
            radius: Theme.radiusSmall
            clip: true

            ListView {
                id: logView
                anchors.fill: parent
                anchors.margins: 1
                clip: true
                model: launcher.logLines
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                delegate: Text {
                    readonly property bool bad: /error|failed|traceback/i.test(modelData)
                    readonly property bool warning: /warn/i.test(modelData)
                    width: logView.width - 18
                    x: 9
                    text: modelData
                    color: bad ? Theme.accent : warning ? Theme.warn : Theme.textDim
                    font.family: Theme.mono
                    font.pixelSize: 10
                    wrapMode: Text.WrapAnywhere
                    topPadding: 1
                    bottomPadding: 1
                }
                onCountChanged: { if (follow.checked) Qt.callLater(positionViewAtEnd) }
                Component.onCompleted: positionViewAtEnd()
            }
            Text {
                anchors.centerIn: parent
                visible: launcher.logLines.length === 0
                text: "No session output yet. Start the game or run a diagnostic."
                color: Theme.textFaint; font.family: Theme.sans; font.pixelSize: 11
            }
            Connections {
                target: launcher
                function onLogChanged() { if (follow.checked) logView.positionViewAtEnd() }
            }
        }
    }
}
