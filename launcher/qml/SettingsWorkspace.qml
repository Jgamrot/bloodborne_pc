import QtQuick
import QtQuick.Controls

// Settings: the categories (and search) on the left, the chosen category on the right: its art,
// its sections as tabs, then the settings of that section. Changes save as they are made.
Item {
    id: workspace
    objectName: "settingsWorkspace"
    signal backToLauncher()
    signal openSetup(int step)
    property string category: "Visuals"
    property string section: ""
    property string targetKey: ""
    property string query: ""
    property var categories: [
        {name: "Visuals", icon: "visuals", tile: "tile-visuals", detail: "Graphics, display & frame rate"},
        {name: "Controls", icon: "controls", tile: "tile-controls", detail: "Prompts, mouse & keyboard"},
        {name: "Game & Saves", icon: "folder", tile: "tile-game-and-saves", detail: "Game files, saves & language"},
        {name: "Online", icon: "online", tile: "tile-online", detail: "Account & connection"},
        {name: "Mods & Patches", icon: "puzzle", tile: "tile-mods-and-patches", detail: "Mods, enhancements & tweaks"},
        {name: "System", icon: "system", tile: "tile-system", detail: "Startup, updates & diagnostics"}
    ]
    property var current: categories.find(c => c.name === category) || categories[0]
    property real listWidth: width < 1200 ? 262 : 300

    function openAt(nextCategory, nextSection, nextKey) {
        category = nextCategory || category || "Visuals"
        section = nextSection || launcher.categorySections(category)[0]
        targetKey = nextKey || ""
        search.text = ""
        detailScroll.contentY = 0
        if (targetKey !== "") Qt.callLater(focusTarget)
    }
    function focusTarget() {
        for (var i = 0; i < fieldRepeater.count; i++) {
            var row = fieldRepeater.itemAt(i)
            if (row && row.settingKey === targetKey) {
                detailScroll.contentY = Math.max(0, row.y - 20)
                break
            }
        }
    }
    function is(cat, sec) { return workspace.category === cat && workspace.section === sec }

    Rectangle { anchors.fill: parent; color: Theme.base }

    // --- The category's art, behind the right side's header -----------------------------------
    Item {
        x: Theme.railWidth + listWidth; width: parent.width - x; height: 230; clip: true
        Image {
            anchors.fill: parent
            source: Qt.resolvedUrl("../assets/ui/" + workspace.current.tile + ".png")
            fillMode: Image.PreserveAspectCrop; horizontalAlignment: Image.AlignRight; verticalAlignment: Image.AlignVCenter
            smooth: true; asynchronous: true; opacity: 0.85
        }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient { orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "#f80b0d10" }
                GradientStop { position: 0.45; color: "#b00b0d10" }
                GradientStop { position: 1; color: "#300b0d10" }
            }
        }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient { GradientStop { position: 0.35; color: "#000b0d10" } GradientStop { position: 1; color: Theme.base } }
        }
    }

    // --- Categories ---------------------------------------------------------------------------
    Rectangle {
        x: Theme.railWidth; width: listWidth; height: parent.height
        color: "#0e1115"
        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.line }
        Column {
            x: 28; y: 34; width: parent.width - 56; spacing: 0
            Item {
                width: parent.width; height: 40
                Row {
                    anchors.verticalCenter: parent.verticalCenter; spacing: 12
                    Text { text: "BLOODBORNE"; color: Theme.text; font.family: Theme.serif; font.pixelSize: 15; font.letterSpacing: 2.2 }
                    Text { text: "/"; color: Theme.textFaint; font.pixelSize: 14 }
                    Text { text: "SETTINGS"; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 12; font.letterSpacing: 2 }
                }
            }
            Rectangle { width: parent.width; height: 1; color: Theme.line }
            Item { width: 1; height: 22 }
            GlassTextField {
                id: search; width: parent.width; height: 40; leftPadding: 40
                placeholderText: "Find a setting"
                onTextChanged: workspace.query = text
                NavIcon { x: 13; anchors.verticalCenter: parent.verticalCenter; width: 17; height: 17; kind: "search"; strokeColor: Theme.textDim }
            }
            Item { width: 1; height: 18 }
            Column {
                width: parent.width; spacing: 6
                Repeater {
                    model: workspace.categories
                    delegate: Rectangle {
                        width: parent.width; height: 62; radius: Theme.radius
                        property bool active: workspace.query === "" && workspace.category === modelData.name
                        color: active || hit.containsMouse ? "#16191d" : "transparent"
                        border.color: active ? Theme.accent : hit.containsMouse ? Theme.line : "transparent"
                        border.width: active ? 1.5 : 1
                        NavIcon { x: 16; anchors.verticalCenter: parent.verticalCenter; width: 22; height: 22; kind: modelData.icon; strokeColor: active ? Theme.text : "#bdb8b0" }
                        Column {
                            x: 54; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 70; spacing: 2
                            Text { text: modelData.name; color: Theme.text; font.family: Theme.serif; font.pixelSize: 17 }
                            Text { width: parent.width; text: modelData.detail; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 12; elide: Text.ElideRight }
                        }
                        MouseArea { id: hit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: workspace.openAt(modelData.name, "", "") }
                    }
                }
            }
        }
        Text {
            x: 28; width: parent.width - 56; anchors.bottom: parent.bottom; anchors.bottomMargin: 22
            text: "Changes save as you make them. Some take effect the next time the game starts."
            color: Theme.textFaint; font.family: Theme.sans; font.pixelSize: 11; wrapMode: Text.WordWrap; lineHeight: 1.3
        }
    }

    // --- The chosen category ------------------------------------------------------------------
    Item {
        id: content
        x: Theme.railWidth + listWidth + 48; y: 0
        width: Math.min(860, parent.width - x - 48); height: parent.height

        // Search results replace the category while there is a query.
        Column {
            visible: workspace.query !== ""
            y: 44; width: parent.width; spacing: 10
            Text { text: "Results"; color: Theme.text; font.family: Theme.serif; font.pixelSize: 36 }
            Text {
                property var hits: launcher.searchSettings(workspace.query)
                visible: hits.length === 0; text: "Nothing matches “" + workspace.query + "”."
                color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 13
            }
            Item { width: 1; height: 8 }
            Repeater {
                model: workspace.query !== "" ? launcher.searchSettings(workspace.query) : []
                delegate: MenuRow {
                    width: content.width; label: modelData.label; value: modelData.category + "  ›  " + modelData.section
                    onClicked: workspace.openAt(modelData.category, modelData.section, modelData.key)
                }
            }
        }

        Column {
            id: header
            visible: workspace.query === ""
            y: 44; width: parent.width; spacing: 6
            Text { text: workspace.category; color: Theme.text; font.family: Theme.serif; font.pixelSize: 42 }
            Text { text: workspace.current.detail; color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 14 }
            Item { width: 1; height: 22 }
            // Sections as tabs: the selected one is underlined in crimson.
            Row {
                spacing: 28
                Repeater {
                    model: launcher.categorySections(workspace.category)
                    delegate: Item {
                        width: tabText.implicitWidth; height: 34
                        property bool active: workspace.section === modelData
                        Text {
                            id: tabText; text: modelData; anchors.top: parent.top
                            color: active ? Theme.text : tabHit.containsMouse ? "#d6d1c9" : Theme.textDim
                            font.family: Theme.sans; font.pixelSize: 14
                        }
                        Rectangle { visible: active; anchors.bottom: parent.bottom; width: parent.width; height: 2; color: Theme.accent }
                        MouseArea { id: tabHit; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: { workspace.section = modelData; detailScroll.contentY = 0 } }
                    }
                }
            }
            Rectangle { width: parent.width; height: 1; color: Theme.line }
        }

        Flickable {
            id: detailScroll
            visible: workspace.query === ""
            y: header.y + header.height + 4; width: parent.width; height: parent.height - y
            clip: true; boundsBehavior: Flickable.StopAtBounds
            contentHeight: detailColumn.implicitHeight + 40
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Column {
                id: detailColumn
                width: detailScroll.width - 14; spacing: 0

                // Graphics presets, above every Visuals section: they rewrite the rows below.
                Item {
                    visible: workspace.category === "Visuals"
                    width: parent.width; height: visible ? presetBox.height + 26 : 0
                    Column {
                        id: presetBox; y: 18; width: parent.width; spacing: 10
                        Row {
                            spacing: 8
                            Text { text: "Preset"; color: Theme.text; font.family: Theme.sans; font.pixelSize: 14; width: 92; anchors.verticalCenter: parent.verticalCenter }
                            Repeater {
                                model: ["low", "balanced", "high", "ultra"]
                                delegate: GlassButton {
                                    width: 104; height: 36
                                    text: launcher.presetLabel(modelData) + (launcher.recommendedPreset === modelData ? "  ★" : "")
                                    highlighted: launcher.graphicsPreset === modelData
                                    onClicked: launcher.applyGraphicsPreset(modelData)
                                }
                            }
                            Text {
                                visible: launcher.graphicsPreset === "custom"; text: "Custom"; leftPadding: 6
                                color: Theme.accentHover; font.family: Theme.sans; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                        Text {
                            x: 100; width: parent.width - 100; wrapMode: Text.WordWrap; lineHeight: 1.3
                            color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 12
                            text: launcher.presetDescription(launcher.graphicsPreset) +
                                  (launcher.recommendedPreset !== "" ? "  ★ Suggested for " + launcher.gpuStatus + "." : "")
                        }
                    }
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                }

                Repeater {
                    id: fieldRepeater
                    // settingsRevision: rebuilt after a preset rewrites several rows.
                    model: launcher.settingsRevision < 0 ? [] : launcher.sectionFields(workspace.category, workspace.section)
                    delegate: FieldRow { width: detailColumn.width; field: modelData }
                }

                // Actions beside the task that calls for them.
                Column {
                    width: parent.width; spacing: 12; topPadding: 20
                    Row { visible: is("Controls", "Button prompts"); spacing: 10
                        Repeater {
                            model: ["PlayStation", "Xbox", "Keyboard"]
                            delegate: GlassButton { text: modelData; width: 124; height: 38; highlighted: launcher.promptChoice === modelData; onClicked: launcher.setPrompt(modelData) }
                        }
                    }
                    Note { visible: is("Controls", "Button prompts"); text: "Which buttons the game shows, from the next start. Both prompt sets come with the launcher, shared with their authors' permission: Xbox by Dommo, Keyboard (PCBButtons) by JinkiJinn. Keyboard also binds the keys its images show: E interact, Left Shift dodge, R blood vial, Q item, F transform, mouse buttons to attack." }
                    Row { visible: is("Visuals", "Upscaling"); spacing: 12
                        GlassButton { text: "Download FSR 4 assets"; width: 190; height: 38; onClicked: launcher.downloadFsr4() }
                        Note { text: launcher.fsrStatus; anchors.verticalCenter: parent.verticalCenter; width: 380 }
                    }
                    Repeater {
                        model: is("Game & Saves", "Game files") ? launcher.readiness.slice(0, 1) :
                               is("Game & Saves", "Your data") ? launcher.readiness.slice(1) : []
                        delegate: Row {
                            spacing: 10
                            Rectangle { width: 8; height: 8; radius: 4; y: 5; color: modelData.level === "error" ? Theme.accent : modelData.level === "warning" ? Theme.warn : Theme.good }
                            Text { width: detailColumn.width - 20; text: modelData.label + ":  " + modelData.detail; color: Theme.text; font.family: Theme.sans; font.pixelSize: 13; wrapMode: Text.WordWrap }
                        }
                    }
                    Row { visible: is("Game & Saves", "Game files"); spacing: 10
                        GlassButton { text: launcher.setupRunning ? "Installing…" : "Install from ZIP / PKG"; width: 196; height: 38; enabled: !launcher.setupRunning && !launcher.running; onClicked: launcher.installFromArchive() }
                        GlassButton { text: "Check again"; width: 120; height: 38; onClicked: launcher.refreshReadiness() }
                        GlassButton { text: "Setup wizard"; width: 128; height: 38; onClicked: workspace.openSetup(0) }
                    }
                    Row { visible: is("Game & Saves", "Your data"); spacing: 10
                        GlassButton { text: "Import trophy keys"; width: 168; height: 38; onClicked: launcher.importTrophyKeys() }
                        GlassButton { text: "Open saves folder"; width: 160; height: 38; onClicked: launcher.action("openSaves") }
                        GlassButton { text: "Check again"; width: 120; height: 38; onClicked: launcher.refreshReadiness() }
                    }
                    Row { visible: is("Online", "Play online"); spacing: 10
                        GlassButton { text: "Create a shadNet account"; width: 210; height: 38; onClicked: launcher.openShadNetRegistration() }
                        GlassButton { text: "Test connection"; width: 148; height: 38; onClicked: launcher.testConnection() }
                    }
                    Note { visible: is("Online", "Play online"); text: "Enter an account ID, not an email address. Test connection checks that the servers answer, not your sign-in." }
                    Note { visible: is("Online", "Play online"); text: "BBSC seamless co-op preview: a separate 0.0.1 BBport test package. Native BBport co-op has not yet been verified by BBSC's author. Its server and account are separate from the normal Online settings." }
                    Row { visible: is("Online", "Play online"); spacing: 10
                        GlassButton { text: "Get BBSC test package"; width: 190; height: 38; onClicked: launcher.openBBSCRelease() }
                        GlassButton { text: "Launch BBSC preview"; width: 185; height: 38; onClicked: launcher.launchBBSCPreview() }
                    }
                    Note { visible: is("Mods & Patches", "Gameplay patches"); text: "Optional gameplay changes. All are off by default and apply the next time the game starts." }
                    Repeater {
                        model: is("Mods & Patches", "Installed mods") ? launcher.contentMods : []
                        delegate: Item {
                            width: detailColumn.width; height: 52
                            GlassSwitch { anchors.verticalCenter: parent.verticalCenter; text: modelData.name; checked: modelData.enabled; onToggled: launcher.setMod(modelData.name, checked) }
                            Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                                GlassButton { text: "↑"; width: 36; height: 32; onClicked: launcher.moveMod(modelData.name, -1) }
                                GlassButton { text: "↓"; width: 36; height: 32; onClicked: launcher.moveMod(modelData.name, 1) }
                            }
                            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
                        }
                    }
                    Note { visible: is("Mods & Patches", "Installed mods") && launcher.contentMods.length === 0; text: "No mods in the mods folder yet. Put each mod in its own folder there, then refresh." }
                    Row { visible: is("Mods & Patches", "Installed mods"); spacing: 10
                        GlassButton { text: "Refresh"; width: 110; height: 38; onClicked: launcher.refresh_addons() }
                        GlassButton { text: "Open mods folder"; width: 160; height: 38; onClicked: launcher.action("openMods") }
                    }
                    Repeater { model: is("Mods & Patches", "External patches") ? launcher.patches : []
                        delegate: GlassSwitch { text: modelData.name; checked: modelData.enabled; onToggled: launcher.setPatch(modelData.name, checked) }
                    }
                    Column { visible: is("System", "Launch"); width: parent.width; spacing: 14
                        Column {
                            width: parent.width
                            ToggleRow { label: "Start the game directly"; hint: "Opening Bloodborne starts the game; hold Shift or Ctrl to open the launcher instead."; checked: launcher.launchDirectly; onToggled: (on) => launcher.setValue("launchDirectly", on) }
                            ToggleRow { label: "Close the launcher after Play"; checked: launcher.closeOnPlay; onToggled: (on) => launcher.setValue("close_on_play", on) }
                        }
                        Row { spacing: 10
                            GlassButton { text: "Desktop shortcut"; width: 156; height: 38; onClicked: launcher.createShortcut() }
                            GlassButton { text: "Add to Steam"; width: 132; height: 38; onClicked: launcher.addToSteam() }
                        }
                    }
                    Column { visible: is("System", "Updates"); width: parent.width; spacing: 14
                        ToggleRow { label: "Check for updates"; hint: "Also checks quietly when the game starts directly, and shows the result here and on Play."; checked: launcher.checked("check_updates"); onToggled: (on) => launcher.setValue("check_updates", on) }
                        Row { spacing: 10
                            GlassButton { visible: launcher.hasUpdate; highlighted: true; text: "Install the new version"; width: 210; height: 38; onClicked: launcher.installUpdate() }
                            GlassButton { text: "Check now"; width: 116; height: 38; onClicked: launcher.checkForUpdates(true) }
                            GlassButton { text: "Releases ↗"; width: 116; height: 38; onClicked: launcher.action("releases") }
                        }
                    }
                    Row { visible: is("System", "Maintenance"); spacing: 10
                        GlassButton { text: "Open port folder"; width: 150; height: 38; onClicked: launcher.action("openPort") }
                        GlassButton { text: "Open bbport.ini"; width: 140; height: 38; onClicked: launcher.action("openConfig") }
                        GlassButton { text: "Clear shader cache"; width: 160; height: 38; onClicked: launcher.action("clearCache") }
                        GlassButton { text: "Setup wizard"; width: 128; height: 38; onClicked: workspace.openSetup(0) }
                    }
                    Row { visible: is("System", "Logs"); spacing: 10
                        GlassButton { text: "Copy log"; width: 110; height: 38; onClicked: launcher.action("copyLog") }
                        GlassButton { text: "Clear log"; width: 110; height: 38; onClicked: launcher.action("clearLog") }
                    }
                    TextArea {
                        visible: is("System", "Logs")
                        width: detailColumn.width; height: visible ? 380 : 0; readOnly: true
                        wrapMode: TextEdit.NoWrap; text: launcher.log; color: Theme.text; selectByMouse: true
                        font.family: "Cascadia Mono"; font.pixelSize: 12
                        background: Rectangle { color: "#0f1216"; radius: Theme.radius; border.color: Theme.line }
                    }
                }
            }
        }
    }
}
