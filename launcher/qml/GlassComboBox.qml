import QtQuick
import QtQuick.Controls

// Flat combobox used by every settings row.
ComboBox {
    id: control
    font.family: Theme.sans
    font.pixelSize: 13
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    implicitHeight: 32
    Accessible.role: Accessible.ComboBox
    background: Rectangle {
        radius: Theme.radiusSmall
        color: control.pressed || control.popup.visible ? Theme.surfaceActive : Theme.surface
        border.color: control.activeFocus || control.popup.visible ? Theme.accent
                      : control.hovered ? Theme.lineStrong : Theme.line
        border.width: 1
    }
    contentItem: Text {
        text: control.displayText
        color: control.enabled ? Theme.text : Theme.textFaint
        font: control.font
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        leftPadding: 10
        rightPadding: 26
    }
    indicator: Canvas {
        width: 9; height: 5
        x: control.width - width - 11; y: (control.height - height) / 2
        onPaint: {
            const c = getContext("2d"); c.reset()
            c.strokeStyle = Theme.textDim; c.lineWidth = 1.3
            c.beginPath(); c.moveTo(0.5, 0.5); c.lineTo(4.5, 4.5); c.lineTo(8.5, 0.5); c.stroke()
        }
    }
    delegate: ItemDelegate {
        width: control.width
        height: 32
        text: modelData.text || ""
        highlighted: control.highlightedIndex === index
        contentItem: Text {
            text: parent.text; leftPadding: 10; verticalAlignment: Text.AlignVCenter
            color: index === control.currentIndex ? Theme.text : Theme.textDim
            font.family: Theme.sans; font.pixelSize: 13
        }
        background: Rectangle {
            color: parent.highlighted ? Theme.surfaceHover : "transparent"
            Rectangle {
                visible: index === control.currentIndex
                width: 2; height: parent.height - 10; anchors.verticalCenter: parent.verticalCenter
                color: Theme.accent
            }
        }
    }
    popup: Popup {
        y: control.height + 3
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 6, 300)
        padding: 3
        contentItem: ListView {
            clip: true; implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
        background: Rectangle { color: Theme.panel; radius: Theme.radiusSmall; border.color: Theme.lineStrong }
    }
}
