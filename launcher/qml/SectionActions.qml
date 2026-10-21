import QtQuick
import QtQuick.Controls

// Actions that belong to a settings section rather than to a single field. Keeping them next
// to their section preserves every operation from the old category workspace.
Column {
    id: actions
    property string category: ""
    property string section: ""
    signal openSetup(int step)
    width: parent ? parent.width : 400
    spacing: 10
    topPadding: 14

    function is(cat, sec) { return actions.category === cat && actions.section === sec }

    // Button prompts.
    Flow {
        visible: actions.is("Controls", "Button prompts")
        width: parent.width; spacing: 8
        Repeater {
            model: ["PlayStation", "Xbox", "Keyboard"]
            delegate: GlassButton {
                text: modelData; width: 118; height: 30
                highlighted: launcher.promptChoice === modelData
                onClicked: launcher.setPrompt(modelData)
            }
        }
    }
    Note {
        visible: actions.is("Controls", "Button prompts")
        text: "The prompt set shown from the next start. Both extra sets ship with the launcher: Xbox by Dommo and the PCBButtons keyboard images by JinkiJinn. Keyboard also binds the keys its images show."
    }

    // FSR 4 assets.
    Flow {
        visible: actions.is("Visuals", "Upscaling")
        width: parent.width; spacing: 10
        GlassButton { text: "Download FSR 4 assets"; height: 30; onClicked: launcher.downloadFsr4() }
        Text {
            width: Math.max(200, actions.width - 190); text: launcher.fsrStatus; color: Theme.textDim
            font.family: Theme.sans; font.pixelSize: 11; wrapMode: Text.WordWrap
        }
    }
    Note {
        visible: actions.is("Visuals", "Upscaling")
        text: "FSR 3.1 is the stable baseline. FSR 4 needs its assets and Intel/AMD INT8 shader support; unavailable providers fall back at runtime."
    }

    // Hunter's Atlas.
    Flow {
        visible: actions.is("Mods & Patches", "Hunter's Atlas (map)")
        width: parent.width; spacing: 10
        GlassButton { text: "Prepare maps"; height: 30; onClicked: launcher.prepareAtlas() }
        Text {
            width: Math.max(220, actions.width - 150); text: launcher.atlasStatus; color: Theme.textDim
            font.family: Theme.sans; font.pixelSize: 11; wrapMode: Text.WordWrap
        }
    }
    Note {
        visible: actions.is("Mods & Patches", "Hunter's Atlas (map)")
        text: "Hunter's Atlas by MikeTat1988 (GPL-2.0): a full-screen map with your position, floors, lamps and NPCs, generated once from your own game files. Open it from the in-game quick menu."
    }

    // Game files.
    Column {
        visible: actions.is("Game & Saves", "Game files")
        width: parent.width; spacing: 8
        Repeater {
            model: actions.is("Game & Saves", "Game files") ? launcher.readiness.slice(0, 1) : []
            delegate: Row {
                width: actions.width; spacing: 8
                Rectangle {
                    width: 7; height: 7; radius: 3.5; y: 5
                    color: modelData.level === "error" ? Theme.accent : modelData.level === "warning" ? Theme.warn : Theme.good
                }
                Text {
                    width: actions.width - 24; text: modelData.label + ":  " + modelData.detail
                    color: Theme.text; font.family: Theme.sans; font.pixelSize: 12; wrapMode: Text.WordWrap
                }
            }
        }
        Flow {
            width: parent.width; spacing: 8
            GlassButton { text: launcher.setupRunning ? "Installing…" : "Install from ZIP / PKG"; height: 30; enabled: !launcher.setupRunning && !launcher.running; onClicked: launcher.installFromArchive() }
            GlassButton { text: "Check again"; height: 30; onClicked: launcher.refreshReadiness() }
            GlassButton { text: "Setup wizard"; height: 30; onClicked: actions.openSetup(0) }
        }
    }

    // Saves and trophy keys.
    Column {
        visible: actions.is("Game & Saves", "Your data")
        width: parent.width; spacing: 8
        Repeater {
            model: actions.is("Game & Saves", "Your data") ? launcher.readiness.slice(1) : []
            delegate: Row {
                width: actions.width; spacing: 8
                Rectangle {
                    width: 7; height: 7; radius: 3.5; y: 5
                    color: modelData.level === "error" ? Theme.accent : modelData.level === "warning" ? Theme.warn : Theme.good
                }
                Text {
                    width: actions.width - 24; text: modelData.label + ":  " + modelData.detail
                    color: Theme.text; font.family: Theme.sans; font.pixelSize: 12; wrapMode: Text.WordWrap
                }
            }
        }
        Flow {
            width: parent.width; spacing: 8
            GlassButton { text: "Import trophy keys"; height: 30; onClicked: launcher.importTrophyKeys() }
            GlassButton { text: "Open saves folder"; height: 30; onClicked: launcher.action("openSaves") }
            GlassButton { text: "Check again"; height: 30; onClicked: launcher.refreshReadiness() }
        }
    }

    // The Hunter's Dream.
    Note {
        visible: actions.is("Online", "The Hunter's Dream")
        text: "The Hunter's Dream (thehuntersdream.com) is the public server for messages, bloodstains, summons and invasions. Sign in once with Discord; choose Online on the Overview page after that. Seamless co-op is separate."
    }
    Note {
        visible: actions.is("Online", "The Hunter's Dream")
        text: launcher.thdStatus; color: Theme.text; font.pixelSize: 12
    }
    Flow {
        visible: actions.is("Online", "The Hunter's Dream") && launcher.thdCode !== ""
        width: parent.width; spacing: 12
        Text {
            text: launcher.thdCode; color: Theme.text; font.family: Theme.mono
            font.pixelSize: 22; font.letterSpacing: 3
        }
        GlassButton { text: "Copy code"; height: 30; onClicked: launcher.thdCopyCode() }
    }
    Flow {
        visible: actions.is("Online", "The Hunter's Dream")
        width: parent.width; spacing: 8
        GlassButton {
            text: launcher.thdBusy ? "Waiting for Discord…" : (launcher.thdSignedIn ? "Sign in again" : "Sign in with Discord")
            width: 180; height: 30; enabled: !launcher.thdBusy; onClicked: launcher.thdSignIn()
        }
        GlassButton { visible: launcher.thdBusy; text: "Cancel"; height: 30; onClicked: launcher.thdCancel() }
        GlassButton { visible: !launcher.thdBusy && launcher.thdSignedIn; text: "Sign out"; height: 30; onClicked: launcher.thdSignOut() }
        GlassButton { text: "Test connection"; height: 30; onClicked: launcher.testConnection() }
    }
    Note {
        visible: actions.is("Online", "The Hunter's Dream")
        text: "The connection is Awaken's port of bbhost's network code (GPL-3.0); bbhost and The Hunter's Dream are by droogie and its team."
    }

    // Seamless co-op.
    Note {
        visible: actions.is("Co-op", "Seamless co-op")
        text: "Experimental. BBSC by CLS_AMG: one session through deaths, lamps, areas and bosses, each hunter keeping their own character. One player hosts; both need Tailscale signed in to the same tailnet. Saves are backed up before every session."
    }
    Note {
        visible: actions.is("Co-op", "Seamless co-op") || actions.is("Co-op", "Host a session") || actions.is("Co-op", "Join a host")
        text: launcher.coopStatus
    }
    Flow {
        visible: actions.is("Co-op", "Seamless co-op")
        width: parent.width; spacing: 8
        GlassButton { text: "Set up co-op"; height: 30; enabled: !launcher.coopBusy; onClicked: launcher.coopSetup() }
        GlassButton { text: "Play co-op"; height: 30; enabled: !launcher.coopBusy && !launcher.running; onClicked: launcher.coopPlay() }
        GlassButton { text: "About BBSC"; height: 30; onClicked: launcher.openCoopHelp() }
    }
    Note {
        visible: actions.is("Co-op", "Host a session")
        text: "Starts BBSC's servers on this PC. Keep the launcher open while you play; closing it stops the servers."
    }
    Flow {
        visible: actions.is("Co-op", "Host a session")
        width: parent.width; spacing: 8
        GlassButton { text: launcher.coopHosting ? "Restart hosting" : "Start hosting"; height: 30; enabled: !launcher.coopBusy; onClicked: launcher.coopStartHosting() }
        GlassButton { text: "Copy invite code"; height: 30; enabled: launcher.coopInvite !== ""; onClicked: launcher.coopCopyInvite() }
        GlassButton { text: "Stop hosting"; height: 30; enabled: launcher.coopHosting; onClicked: launcher.coopStopHosting() }
    }
    Note {
        visible: actions.is("Co-op", "Join a host")
        text: "Paste the invite code from your host, then choose Play co-op on the Overview page. The host rings the Hunt Bell; you ring the Kin Bell."
    }

    // Mods.
    Column {
        visible: actions.is("Mods & Patches", "Installed mods")
        width: parent.width; spacing: 0
        Repeater {
            model: actions.is("Mods & Patches", "Installed mods") ? launcher.contentMods : []
            delegate: Item {
                width: actions.width; height: 38
                GlassSwitch {
                    width: parent.width - 86; anchors.verticalCenter: parent.verticalCenter
                    text: modelData.name; checked: modelData.enabled
                    onToggled: launcher.setMod(modelData.name, checked)
                }
                Row {
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                    GlassButton { text: "↑"; width: 30; height: 26; onClicked: launcher.moveMod(modelData.name, -1) }
                    GlassButton { text: "↓"; width: 30; height: 26; onClicked: launcher.moveMod(modelData.name, 1) }
                }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
            }
        }
        Text {
            visible: launcher.contentMods.length === 0
            text: "No mods in the mods folder yet. Put each mod in its own folder there, then refresh."
            color: Theme.textDim; font.family: Theme.sans; font.pixelSize: 12; wrapMode: Text.WordWrap
            width: parent.width
        }
        Item { width: 1; height: 8 }
        Flow {
            width: parent.width; spacing: 8
            GlassButton { text: "Refresh"; height: 30; onClicked: launcher.refresh_addons() }
            GlassButton { text: "Open mods folder"; height: 30; onClicked: launcher.action("openMods") }
        }
    }
    Column {
        visible: actions.is("Mods & Patches", "External patches")
        width: parent.width; spacing: 0
        Repeater {
            model: actions.is("Mods & Patches", "External patches") ? launcher.patches : []
            delegate: Item {
                width: actions.width; height: 34
                GlassSwitch {
                    width: parent.width; anchors.verticalCenter: parent.verticalCenter
                    text: modelData.name; checked: modelData.enabled
                    onToggled: launcher.setPatch(modelData.name, checked)
                }
                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.line }
            }
        }
    }
    Note {
        visible: actions.is("Mods & Patches", "Gameplay patches")
        text: "Optional gameplay changes. All are off by default and apply the next time the game starts."
    }

    // System: startup behavior.
    Column {
        visible: actions.is("System", "Launch")
        width: parent.width; spacing: 4
        ToggleRow {
            label: "Start the game directly"
            hint: "Opening Bloodborne starts the game; hold Shift or Ctrl for the launcher."
            checked: launcher.launchDirectly
            onToggled: (on) => launcher.setValue("launchDirectly", on)
        }
        ToggleRow {
            label: "Close the launcher after Play"
            checked: launcher.closeOnPlay
            onToggled: (on) => launcher.setValue("close_on_play", on)
        }
        Item { width: 1; height: 6 }
        Flow {
            width: parent.width; spacing: 8
            GlassButton { text: "Desktop shortcut"; height: 30; onClicked: launcher.createShortcut() }
            GlassButton { text: "Add to Steam"; height: 30; onClicked: launcher.addToSteam() }
        }
    }

    // System: updates.
    Column {
        visible: actions.is("System", "Updates")
        width: parent.width; spacing: 8
        ToggleRow {
            label: "Check for updates"
            hint: "Also checks quietly after a direct launch and shows the result on Overview."
            checked: launcher.checked("check_updates")
            onToggled: (on) => launcher.setValue("check_updates", on)
        }
        Flow {
            width: parent.width; spacing: 8
            GlassButton { visible: launcher.hasUpdate; highlighted: true; text: "Install " + (launcher.updateVersion || "update"); height: 30; onClicked: launcher.installUpdate() }
            GlassButton { text: "Check now"; height: 30; onClicked: launcher.checkForUpdates(true) }
            GlassButton { text: "Releases"; height: 30; onClicked: launcher.action("releases") }
        }
    }

    // System: maintenance.
    Flow {
        visible: actions.is("System", "Maintenance")
        width: parent.width; spacing: 8
        GlassButton { text: "Open port folder"; height: 30; onClicked: launcher.action("openPort") }
        GlassButton { text: "Open bbport.ini"; height: 30; onClicked: launcher.action("openConfig") }
        GlassButton { text: "Clear shader cache"; height: 30; onClicked: launcher.action("clearCache") }
        GlassButton { text: "Setup wizard"; height: 30; onClicked: actions.openSetup(0) }
    }
}
