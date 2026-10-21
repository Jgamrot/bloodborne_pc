import QtQuick

// Line icons on a 24 × 24 grid, drawn at any size with the same stroke weight.
Canvas {
    id: icon
    property string kind: "home"
    property color strokeColor: Theme.text
    property real stroke: 1.6
    width: 24
    height: 24
    onKindChanged: requestPaint()
    onStrokeColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        const c = getContext("2d")
        c.reset()
        const s = Math.min(width, height) / 24
        c.scale(s, s)
        c.strokeStyle = strokeColor
        c.fillStyle = strokeColor
        c.lineWidth = stroke / s
        c.lineCap = "round"
        c.lineJoin = "round"
        function line(p) { c.beginPath(); c.moveTo(p[0], p[1]); for (let i = 2; i < p.length; i += 2) c.lineTo(p[i], p[i + 1]); c.stroke() }
        function shape(p) { c.beginPath(); c.moveTo(p[0], p[1]); for (let i = 2; i < p.length; i += 2) c.lineTo(p[i], p[i + 1]); c.closePath(); c.stroke() }
        function circle(x, y, r) { c.beginPath(); c.arc(x, y, r, 0, 2 * Math.PI); c.stroke() }
        function dot(x, y, r) { c.beginPath(); c.arc(x, y, r, 0, 2 * Math.PI); c.fill() }
        function rect(x, y, w, h) { c.beginPath(); c.rect(x, y, w, h); c.stroke() }
        switch (kind) {
        case "hunter": // the guide's mark: a blade crossed with a compass rose
            line([12, 1.5, 12, 22.5]); line([3.5, 12, 20.5, 12])
            shape([12, 5, 15, 12, 12, 19, 9, 12]); line([9.5, 20, 12, 22.5, 14.5, 20]); break
        case "overview": case "home":
            line([3, 11, 12, 3.5, 21, 11]); line([5, 9.5, 5, 21, 19, 21, 19, 9.5]); rect(10, 14.5, 4, 6.5); break
        case "play":
            shape([7, 4.5, 19, 12, 7, 19.5]); break
        case "settings": case "system": case "advanced":
            circle(12, 12, 3.2)
            for (let a = 0; a < 8; a++) { const t = a * Math.PI / 4; line([12 + 6.4 * Math.cos(t), 12 + 6.4 * Math.sin(t), 12 + 9 * Math.cos(t), 12 + 9 * Math.sin(t)]) }
            circle(12, 12, 6.4); break
        case "trophy": case "achievements":
            line([7, 3.5, 17, 3.5, 16.5, 11, 14, 14, 10, 14, 7.5, 11, 7, 3.5])
            line([7, 6, 3.5, 6, 4.5, 10, 7.6, 11.4]); line([17, 6, 20.5, 6, 19.5, 10, 16.4, 11.4])
            line([12, 14, 12, 18]); line([8, 20.5, 16, 20.5]); line([9.5, 18, 14.5, 18]); break
        case "puzzle": case "mods": case "mods-and-patches": // a jigsaw piece with a knob on top and right
            c.beginPath(); c.moveTo(4, 7.5); c.lineTo(9.2, 7.5)
            c.bezierCurveTo(8.2, 5.8, 8.6, 3.5, 11, 3.5); c.bezierCurveTo(13.4, 3.5, 13.8, 5.8, 12.8, 7.5)
            c.lineTo(17.5, 7.5); c.lineTo(17.5, 11.7)
            c.bezierCurveTo(19.2, 10.7, 21.5, 11.1, 21.5, 13.5); c.bezierCurveTo(21.5, 15.9, 19.2, 16.3, 17.5, 15.3)
            c.lineTo(17.5, 20.5); c.lineTo(4, 20.5); c.closePath(); c.stroke(); break
        case "visuals": case "display":
            rect(2.5, 4, 19, 13); line([8.5, 21, 15.5, 21]); line([12, 17, 12, 21]); break
        case "graphics":
            rect(4, 4, 16, 16); rect(8, 8, 8, 8)
            line([4, 1.5, 4, 4]); line([20, 1.5, 20, 4]); line([4, 20, 4, 22.5]); line([20, 20, 20, 22.5])
            line([1.5, 4, 4, 4]); line([1.5, 20, 4, 20]); line([20, 4, 22.5, 4]); line([20, 20, 22.5, 20]); break
        case "controls": case "controller":
            c.beginPath(); c.moveTo(6.5, 7.5); c.lineTo(17.5, 7.5); c.quadraticCurveTo(21, 8.5, 22, 15)
            c.quadraticCurveTo(22.5, 20, 19, 19.5); c.lineTo(15.5, 16.5); c.lineTo(8.5, 16.5); c.lineTo(5, 19.5)
            c.quadraticCurveTo(1.5, 20, 2, 15); c.quadraticCurveTo(3, 8.5, 6.5, 7.5); c.stroke()
            line([6, 12, 10, 12]); line([8, 10, 8, 14]); dot(16, 11, 1); dot(18.5, 13.5, 1); break
        case "folder": case "game-and-saves":
            line([2.5, 6, 2.5, 19.5, 21.5, 19.5, 21.5, 8, 11, 8, 9, 5, 2.5, 5, 2.5, 6]); line([8.5, 13.5, 11, 16, 16, 11]); break
        case "online": case "globe":
            circle(12, 12, 9); line([3, 12, 21, 12])
            c.beginPath(); c.ellipse(8, 3, 8, 18); c.stroke(); break
        case "update":
            c.beginPath(); c.arc(12, 12, 8, -Math.PI * 0.35, Math.PI * 1.45); c.stroke()
            line([12, 7.5, 12, 15]); line([8.5, 12, 12, 15.5, 15.5, 12]); break
        case "chevron":
            line([9, 5, 16, 12, 9, 19]); break
        case "back":
            line([15, 5, 8, 12, 15, 19]); break
        case "search":
            circle(10.5, 10.5, 6); line([15, 15, 20.5, 20.5]); break
        case "log":
            rect(4.5, 2.5, 15, 19); line([8, 8, 16, 8]); line([8, 12, 16, 12]); line([8, 16, 13, 16]); break
        case "close":
            line([6, 6, 18, 18]); line([18, 6, 6, 18]); break
        default:
            circle(12, 12, 8)
        }
    }
}
