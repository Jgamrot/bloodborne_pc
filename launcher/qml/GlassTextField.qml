import QtQuick
import QtQuick.Controls

// Flat text field used by settings, search and co-op codes.
TextField {
    id: control
    color: Theme.text
    placeholderTextColor: Theme.textFaint
    selectedTextColor: "#ffffff"
    selectionColor: "#7e2833"
    font.family: Theme.sans
    font.pixelSize: 13
    leftPadding: 10
    rightPadding: 10
    implicitHeight: 32
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.EditableText
    background: Rectangle {
        radius: Theme.radiusSmall
        color: Theme.surface
        border.color: control.activeFocus ? Theme.accent : control.hovered ? Theme.lineStrong : Theme.line
        border.width: 1
    }
}
