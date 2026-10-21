import QtQuick

// Persistent application navigation. Unlike the old icon-only rail, every destination is named
// so the launcher reads like a desktop utility rather than a game menu.
Rectangle {
    id: rail
    property string current: "Home"
    property bool locked: false       // first-time setup: no navigation until it finishes or skips
    signal navigate(string page)
    width: Theme.railWidth
    color: Theme.panel
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }

    Column {
        x: 18; y: 20; width: parent.width - 36; spacing: 0
        Row {
            width: parent.width; spacing: 11
            Image {
                width: 36; height: 36
                source: Qt.resolvedUrl("../assets/hunter-icon.png")
                fillMode: Image.PreserveAspectCrop; smooth: true; mipmap: true
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter; spacing: 2
                Text {
                    text: "BLOODBORNE"; color: Theme.text; font.family: Theme.serif
                    font.pixelSize: 15; font.letterSpacing: 1.8
                }
                Text {
                    text: "WINDOWS PORT"; color: Theme.textFaint; font.family: Theme.sans
                    font.pixelSize: 10; font.letterSpacing: 1.4
                }
            }
        }
        Item { width: 1; height: 22 }
        Rectangle { width: parent.width; height: 1; color: Theme.line }
        Item { width: 1; height: 12 }

        Text {
            visible: rail.locked
            width: parent.width; text: "FIRST-TIME SETUP"; color: Theme.accent
            font.family: Theme.sans; font.pixelSize: 10; font.letterSpacing: 1.4
        }

        Repeater {
            model: rail.locked ? [] : [
                {kind: "overview", page: "Home", label: "Overview"},
                {kind: "graphics", page: "Graphics", label: "Graphics"},
                {kind: "display", page: "Display", label: "Display"},
                {kind: "folder", page: "Game", label: "Game & saves"},
                {kind: "puzzle", page: "Mods", label: "Mods & patches"},
                {kind: "online", page: "Online", label: "Online"},
                {kind: "system", page: "System", label: "System"},
                {kind: "log", page: "Logs", label: "Diagnostics"}
            ]
            delegate: Rectangle {
                id: navRow
                width: parent.width; height: 36; radius: Theme.radiusSmall
                property bool active: rail.current === modelData.page
                color: active ? Theme.surfaceActive : hit.containsMouse ? Theme.surfaceHover : "transparent"
                Rectangle {
                    visible: navRow.active
                    width: 2; height: parent.height - 12; anchors.verticalCenter: parent.verticalCenter
                    color: Theme.accent
                }
                NavIcon {
                    x: 12; anchors.verticalCenter: parent.verticalCenter; width: 17; height: 17
                    kind: modelData.kind; strokeColor: navRow.active ? Theme.text : Theme.textDim
                }
                Text {
                    x: 38; anchors.verticalCenter: parent.verticalCenter
                    text: modelData.label; color: navRow.active ? Theme.text : Theme.textDim
                    font.family: Theme.sans; font.pixelSize: 13
                }
                MouseArea {
                    id: hit; anchors.fill: parent; hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: rail.navigate(modelData.page)
                }
                Accessible.role: Accessible.PageTab
                Accessible.name: modelData.label
            }
        }
    }

    Column {
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        anchors.leftMargin: 18; anchors.rightMargin: 18; anchors.bottomMargin: 16; spacing: 6
        Rectangle { width: parent.width; height: 1; color: Theme.line }
        Text {
            text: "v" + launcher.version + "  ·  " + (launcher.launchState === "running" ? "Game running" :
                  launcher.launchState === "starting" ? "Starting game" :
                  launcher.launchState === "preparing" ? "Preparing game" :
                  launcher.launchState === "failed" ? "Last launch failed" : "Ready")
            color: launcher.launchState === "failed" ? Theme.accent :
                   launcher.launchState === "running" ? Theme.good : Theme.textFaint
            font.family: Theme.sans; font.pixelSize: 10
        }
        Text {
            text: "Changes save automatically"; color: Theme.textFaint
            font.family: Theme.sans; font.pixelSize: 10
        }
    }
}
