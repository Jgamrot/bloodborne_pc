pragma Singleton
import QtQuick

// Design tokens for the Windows launcher: graphite surfaces, warm text and a single crimson
// accent. The launcher is a technical utility; hierarchy comes from type and spacing, not
// glass, gradients or card stacks.
QtObject {
    readonly property color base: "#0b0d10"
    readonly property color panel: "#101419"
    readonly property color surface: "#151a20"
    readonly property color surfaceHover: "#1c222a"
    readonly property color surfaceActive: "#222a33"
    readonly property color line: "#242b34"
    readonly property color lineStrong: "#35404b"
    readonly property color text: "#e9e6df"
    readonly property color textDim: "#9aa4ae"
    readonly property color textFaint: "#68727c"
    readonly property color accent: "#b53846"
    readonly property color accentHover: "#c94a58"
    readonly property color accentSoft: "#2a1519"
    readonly property color good: "#82b98f"
    readonly property color warn: "#d6a75c"
    readonly property color info: "#7fa6c4"

    readonly property string serif: "Georgia"
    readonly property string sans: "Segoe UI"
    readonly property string mono: "Cascadia Mono"

    readonly property int railWidth: 220
    readonly property int topBarHeight: 56
    readonly property int footerHeight: 30
    readonly property int radius: 4
    readonly property int radiusSmall: 3
    readonly property int rowHeight: 54
    readonly property int pageMaxWidth: 1120
    readonly property int pagePadding: 32
}
