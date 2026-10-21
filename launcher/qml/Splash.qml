import QtQuick
import QtQuick.Window

// Shown instead of the launcher during a direct launch. It never takes focus from the game.
Window {
    id: splash
    objectName: "launchSplash"
    signal openLauncher()
    // Seconds before the game starts (set by bbport_launcher_qml.py); 0 once it is starting.
    property int countdown: 0
    visible: true
    width: 460; height: 104
    x: Screen.virtualX + (Screen.desktopAvailableWidth - width) / 2
    y: Screen.virtualY + (Screen.desktopAvailableHeight - height) / 2
    flags: Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
    color: "transparent"
    title: "Bloodborne"

    Rectangle {
        anchors.fill: parent
        radius: Theme.radius
        color: Theme.panel
        border.color: Theme.lineStrong
        Rectangle { width: 3; height: parent.height - 24; anchors.left: parent.left; anchors.leftMargin: 10; anchors.verticalCenter: parent.verticalCenter; color: Theme.accent }
        Image {
            x: 28; anchors.verticalCenter: parent.verticalCenter
            width: 46; height: 46
            source: Qt.resolvedUrl("../assets/hunter-icon.png")
            fillMode: Image.PreserveAspectCrop; smooth: true; mipmap: true
        }
        Column {
            x: 90; anchors.verticalCenter: parent.verticalCenter; spacing: 5
            Text {
                text: splash.countdown > 0 ? "Bloodborne starts in " + splash.countdown + "…" : "Starting Bloodborne…"
                color: Theme.text; font.family: Theme.sans; font.pixelSize: 16; font.weight: Font.DemiBold
            }
            Text {
                text: "Hold Shift or click here for the launcher"
                color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11
            }
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: splash.openLauncher() }
    }
}
