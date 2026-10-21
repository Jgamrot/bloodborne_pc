import QtQuick
import QtQuick.Controls

// Shared launcher button. `highlighted` is the single primary action on a page; everything
// else is a quiet outline. `serif` is retained for the large launch action and setup title.
Button {
    id: button
    property bool primary: highlighted
    property bool serif: false
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    font.family: serif ? Theme.serif : Theme.sans
    font.pixelSize: serif ? 15 : 12.5
    font.weight: serif ? Font.Normal : Font.DemiBold
    font.letterSpacing: serif ? 0.4 : 0.2
    leftPadding: 14
    rightPadding: 14
    topPadding: 0
    bottomPadding: 0
    implicitHeight: 34
    Accessible.role: Accessible.Button
    Accessible.name: text
    contentItem: Text {
        text: button.text
        font: button.font
        color: !button.enabled ? Theme.textFaint : Theme.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: Theme.radiusSmall
        color: button.primary
               ? (!button.enabled ? Theme.accentSoft : button.down ? "#9c2d3a" : button.hovered ? Theme.accentHover : Theme.accent)
               : (!button.enabled ? "transparent" : button.down ? Theme.surfaceActive : button.hovered ? Theme.surfaceHover : "transparent")
        border.color: button.primary ? (button.enabled ? "transparent" : Theme.line)
                                     : (button.hovered ? Theme.lineStrong : Theme.line)
        border.width: 1
        Behavior on color { ColorAnimation { duration: 90 } }
    }
}
