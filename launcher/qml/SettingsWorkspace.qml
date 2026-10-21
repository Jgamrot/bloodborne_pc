import QtQuick
import QtQuick.Controls

// Settings page: one top-level page, its sections stacked in reading order. Every value saves
// as it changes; the page is a view over the backend, not the owner of process state.
Item {
    id: workspace
    property string pageKey: "Graphics"
    property string query: ""
    property string targetCategory: ""
    property string targetSection: ""
    property string targetKey: ""
    property int settingsRevision: launcher.settingsRevision
    property var groups: launcher.pageSections(pageKey)
    onPageKeyChanged: {
        launcher.debugPage("settings page=" + pageKey)
        detailScroll.contentY = 0
    }
    signal openPage(string page, string category, string section, string key)
    signal openSetup(int step)

    function openAt(category, section, key) {
        targetCategory = category || ""
        targetSection = section || ""
        targetKey = key || ""
        Qt.callLater(scrollToTarget)
    }
    function scrollToTarget() {
        if (targetCategory === "" && targetSection === "") return
        for (let i = 0; i < groupRepeater.count; i++) {
            const item = groupRepeater.itemAt(i)
            if (!item || !item.group) continue
            if (item.group.category === targetCategory && item.group.section === targetSection) {
                detailScroll.contentY = Math.max(0, item.y - 10)
                return
            }
        }
    }

    Rectangle { anchors.fill: parent; color: Theme.base }

    Flickable {
        id: detailScroll
        x: Math.max(28, (workspace.width - width) / 2)
        width: Math.min(Theme.pageMaxWidth, workspace.width - 56)
        height: workspace.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        contentWidth: width
        contentHeight: pageContent.implicitHeight + 48
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
            id: pageContent
            width: detailScroll.width
            spacing: 0

            // Search results replace the settings list while a query is active.
            Column {
                visible: workspace.query !== ""
                width: parent.width
                spacing: 0
                Item { width: 1; height: 6 }
                Text {
                    text: "SEARCH RESULTS"; color: Theme.textFaint; font.family: Theme.sans
                    font.pixelSize: 10; font.letterSpacing: 1.3
                }
                Item { width: 1; height: 6 }
                Rectangle { width: parent.width; height: 1; color: Theme.line }
                Repeater {
                    model: workspace.query !== "" ? launcher.searchSettings(workspace.query) : []
                    delegate: MenuRow {
                        width: pageContent.width
                        label: modelData.label
                        value: launcher.pageFor(modelData.category, modelData.section) + "  ·  " + modelData.section
                        icon: ""
                        onClicked: workspace.openPage(launcher.pageFor(modelData.category, modelData.section),
                                                      modelData.category, modelData.section, modelData.key)
                    }
                }
                Text {
                    visible: workspace.query !== "" && launcher.searchSettings(workspace.query).length === 0
                    text: "Nothing matches “" + workspace.query + "”."
                    color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 12
                    topPadding: 12
                }
            }

            Column {
                visible: workspace.query === ""
                width: parent.width
                spacing: 0

                Item { width: 1; height: 4 }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: "Changes save as you make them. Options marked as restart apply at the next launch."
                    color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11
                }
                Item { width: 1; height: 14 }

                // Graphics presets rewrite several fields at once.
                Column {
                    visible: workspace.pageKey === "Graphics"
                    width: parent.width
                    spacing: 8
                    Text {
                        text: "GRAPHICS PRESET"; color: Theme.textFaint; font.family: Theme.sans
                        font.pixelSize: 10; font.letterSpacing: 1.3
                    }
                    Flow {
                        width: parent.width; spacing: 8
                        Repeater {
                            model: ["low", "balanced", "high", "ultra"]
                            delegate: GlassButton {
                                width: 98; height: 30
                                text: launcher.presetLabel(modelData)
                                highlighted: launcher.graphicsPreset === modelData
                                onClicked: launcher.applyGraphicsPreset(modelData)
                            }
                        }
                        Text {
                            visible: launcher.graphicsPreset === "custom"
                            text: "Custom"; color: Theme.accent
                            font.family: Theme.sans; font.pixelSize: 12
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: launcher.presetDescription(launcher.graphicsPreset) +
                              (launcher.recommendedPreset !== "" ? "  Suggested for the detected card." : "")
                        color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11
                        lineHeight: 1.3
                    }
                    Item { width: 1; height: 8 }
                    Rectangle { width: parent.width; height: 1; color: Theme.line }
                    Item { width: 1; height: 14 }
                }

                Repeater {
                    id: groupRepeater
                    model: workspace.groups
                    delegate: Column {
                        id: groupColumn
                        property var group: modelData
                        width: pageContent.width
                        spacing: 0

                        Item { width: 1; height: 12 }
                        Text {
                            text: groupColumn.group.title; color: Theme.text
                            font.family: Theme.sans; font.pixelSize: 15; font.weight: Font.DemiBold
                        }
                        Text {
                            visible: (groupColumn.group.hint || "") !== ""
                            width: parent.width; text: groupColumn.group.hint || ""
                            color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 11
                            wrapMode: Text.WordWrap; lineHeight: 1.3; topPadding: 3
                        }
                        Item { width: 1; height: 8 }

                        Repeater {
                            model: workspace.settingsRevision < 0 ? [] :
                                   launcher.sectionFields(groupColumn.group.category, groupColumn.group.section)
                            delegate: FieldRow { width: groupColumn.width; field: modelData }
                        }

                        SectionActions {
                            width: groupColumn.width
                            category: groupColumn.group.category
                            section: groupColumn.group.section
                            onOpenSetup: (step) => workspace.openSetup(step)
                        }

                        Item { width: 1; height: 12 }
                        Rectangle { width: parent.width; height: 1; color: Theme.line }
                    }
                }
                Item { width: 1; height: 20 }
            }
        }
    }
}
