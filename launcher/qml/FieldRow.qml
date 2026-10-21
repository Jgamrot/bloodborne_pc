import QtQuick
import QtQuick.Controls

// One setting: label and hint on the left, control on the right, a hairline below.
Item {
    id: fieldRow
    property var field: ({})
    property string settingKey: field.key || ""
    property bool hasHint: (field.hint || "") !== ""
    property bool isFolder: field.kind === "folder"
    property real controlWidth: Math.min(320, width * 0.46)
    implicitHeight: isFolder ? 70 : Math.max(50, labels.implicitHeight + 18)
    height: implicitHeight

    Column {
        id: labels
        x: 0
        y: isFolder || hasHint ? 10 : (parent.height - height) / 2
        width: Math.max(160, parent.width - fieldRow.controlWidth - 28)
        spacing: 3
        Text {
            width: parent.width; text: field.label || ""; color: Theme.text; elide: Text.ElideRight
            font.family: Theme.sans; font.pixelSize: 13
        }
        Text {
            visible: hasHint; width: parent.width; text: field.hint || ""; color: Theme.textDim
            font.family: Theme.sans; font.pixelSize: 11; wrapMode: Text.WordWrap
            maximumLineCount: 2; elide: Text.ElideRight; lineHeight: 1.25
        }
    }

    GlassSwitch {
        visible: field.kind === "toggle"
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        text: ""
        checked: launcher.checked(settingKey)
        Accessible.name: fieldRow.field.label || ""
        onToggled: launcher.setValue(settingKey, checked)
    }

    GlassComboBox {
        visible: field.kind === "choice"
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        width: fieldRow.controlWidth; height: 32
        model: field.options || []
        textRole: "text"
        valueRole: "value"
        Accessible.name: fieldRow.field.label || ""
        Component.onCompleted: currentIndex = indexOfValue(String(launcher.value(settingKey)))
        onActivated: launcher.setValue(settingKey, currentValue)
    }

    Row {
        visible: field.kind !== "toggle" && field.kind !== "choice"
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        width: fieldRow.controlWidth; spacing: 6
        GlassTextField {
            width: fieldRow.isFolder ? parent.width - 88 : parent.width
            height: 32
            text: String(launcher.value(settingKey))
            placeholderText: fieldRow.isFolder ? "Default location" : ""
            echoMode: field.kind === "password" ? TextInput.Password : TextInput.Normal
            Accessible.name: fieldRow.field.label || ""
            onTextEdited: launcher.setValue(settingKey, text)
            onEditingFinished: launcher.setValue(settingKey, text)
            onActiveFocusChanged: { if (!activeFocus) cursorPosition = 0 }
            Component.onCompleted: cursorPosition = 0
        }
        GlassButton {
            visible: fieldRow.isFolder
            width: 82; height: 32; text: "Browse"
            onClicked: launcher.browse(settingKey)
        }
    }

    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
}
