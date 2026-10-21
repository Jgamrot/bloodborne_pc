import QtQuick

// Explanatory text under a section's settings.
Text {
    width: parent ? parent.width : 400
    color: Theme.textDim
    font.family: Theme.sans
    font.pixelSize: 12
    wrapMode: Text.WordWrap
    lineHeight: 1.35
}
