import QtQuick
import QtQuick.Controls

// Compact switch. State changes immediately; only the colour eases.
Switch {
    id: control
    spacing: 10
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    font.family: Theme.sans
    font.pixelSize: 13
    implicitHeight: 28
    Accessible.role: Accessible.CheckBox
    Accessible.name: text
    contentItem: Text {
        text: control.text
        color: control.enabled ? Theme.text : Theme.textFaint
        font: control.font
        leftPadding: control.indicator.width + control.spacing
        verticalAlignment: Text.AlignVCenter
    }
    indicator: Rectangle {
        implicitWidth: 32
        implicitHeight: 18
        x: control.leftPadding
        y: (control.height - height) / 2
        radius: 9
        color: control.checked ? Theme.accent : (control.hovered ? Theme.surfaceActive : Theme.surface)
        border.color: control.checked ? Theme.accent : Theme.lineStrong
        Rectangle {
            width: 12; height: 12; radius: 6
            x: control.checked ? parent.width - width - 3 : 3
            y: 3
            color: control.checked ? "#fff6f2" : Theme.textDim
        }
    }
}
