import QtQuick

// A launcher toggle laid out like a setting row: label and hint left, switch right.
Item {
    id: row
    property string label: ""
    property string hint: ""
    property bool checked: false
    signal toggled(bool checked)
    width: parent ? parent.width : 400
    height: Math.max(50, texts.implicitHeight + 18)
    Column {
        id: texts; x: 0; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 70; spacing: 3
        Text { width: parent.width; text: row.label; color: Theme.text; font.family: Theme.sans; font.pixelSize: 13; elide: Text.ElideRight }
        Text { visible: row.hint !== ""; width: parent.width; text: row.hint; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11; wrapMode: Text.WordWrap; lineHeight: 1.25 }
    }
    GlassSwitch {
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        text: ""
        checked: row.checked
        Accessible.name: row.label
        onToggled: row.toggled(checked)
    }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
}
