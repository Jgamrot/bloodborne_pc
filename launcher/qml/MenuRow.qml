import QtQuick

// A flat navigation / quick-action row: icon, label, value, chevron. No card chrome.
Rectangle {
    id: row
    property string icon: ""
    property string label: ""
    property string value: ""
    property color valueColor: Theme.textDim
    property bool selected: false
    property bool chevron: true
    signal clicked()
    height: 48; radius: Theme.radiusSmall
    color: hit.containsMouse ? Theme.surfaceHover : "transparent"
    Rectangle {
        visible: row.selected
        width: 2; height: parent.height - 12; anchors.verticalCenter: parent.verticalCenter
        color: Theme.accent
    }

    NavIcon {
        id: glyph; visible: row.icon !== ""
        x: 14; anchors.verticalCenter: parent.verticalCenter; width: 19; height: 19
        kind: row.icon; strokeColor: row.selected ? Theme.text : Theme.textDim
    }
    Text {
        x: row.icon !== "" ? 46 : 14; anchors.verticalCenter: parent.verticalCenter
        width: parent.width - x - valueText.width - 42
        text: row.label; color: Theme.text; elide: Text.ElideRight
        font.family: Theme.sans; font.pixelSize: 13
    }
    Text {
        id: valueText
        anchors.right: parent.right; anchors.rightMargin: row.chevron ? 32 : 14; anchors.verticalCenter: parent.verticalCenter
        width: Math.min(implicitWidth, row.width * 0.44)
        text: row.value; color: row.valueColor; elide: Text.ElideRight
        font.family: Theme.sans; font.pixelSize: 12
    }
    NavIcon {
        visible: row.chevron
        anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
        width: 14; height: 14; kind: "chevron"; strokeColor: Theme.textFaint; stroke: 1.6
    }
    MouseArea {
        id: hit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
        onClicked: row.clicked()
    }
    Accessible.role: Accessible.Button
    Accessible.name: row.label
}
