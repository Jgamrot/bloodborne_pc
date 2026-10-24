import QtQuick
import QtQuick.Controls

// One action of Controls > Key bindings: its name and up to three bindings, each a key, a mouse
// button or a combination ("Shift + Left click"). A left click on a slot captures the next key
// or mouse button, a right click clears it.
Item {
    id: bindRow
    property var row: ({})
    signal captureRequested(string action, int slot, string label)
    width: parent ? parent.width : 0
    height: 56

    Text {
        id: name
        x: 2
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(120, bindRow.width - slots.width - 24)
        text: bindRow.row.label || ""
        color: Theme.text
        font.family: Theme.sans
        font.pixelSize: 14
        elide: Text.ElideRight
    }

    Row {
        id: slots
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8
        Repeater {
            model: bindRow.row.slots || []
            delegate: Rectangle {
                id: slotButton
                required property var modelData
                required property int index
                width: 152; height: 36; radius: Theme.radius
                color: hover.containsMouse ? Theme.surfaceHover : Theme.surface
                border.width: 1
                border.color: hover.containsMouse ? Theme.lineStrong : Theme.line
                Text {
                    anchors.centerIn: parent
                    width: parent.width - 16
                    horizontalAlignment: Text.AlignHCenter
                    text: slotButton.modelData.text
                    color: slotButton.modelData.bound ? Theme.text : Theme.textFaint
                    font.family: Theme.sans
                    font.pixelSize: 13
                    elide: Text.ElideRight
                }
                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onClicked: (mouse) => {
                        if (mouse.button === Qt.RightButton) {
                            if (slotButton.modelData.bound) launcher.clearBinding(bindRow.row.action, slotButton.index)
                        } else {
                            bindRow.captureRequested(bindRow.row.action, slotButton.index, bindRow.row.label)
                        }
                    }
                }
            }
        }
    }

    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
}
