import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.VectorImage

Window {
    id: root
    required property var backend
    property bool startFullScreen: true
    property int initialWidth: 1280
    property int initialHeight: 720
    property bool touchDebugEnabled: false
    property int touchRotation: 0

    width: initialWidth
    height: initialHeight
    visible: true
    visibility: startFullScreen ? Window.FullScreen : Window.Windowed
    color: "#000000"
    title: "Photo Frame - PySide6 + Qt Quick"

    readonly property bool isPortrait: root.height >= root.width
    readonly property bool useQrcAssets: root.backend.weatherIcon.indexOf("qrc:/") === 0
    readonly property int actionButtonSize: root.isPortrait ? 60 : 50
    readonly property int actionIconSize: root.isPortrait ? 29 : 24
    readonly property int actionBusySize: root.isPortrait ? 28 : 24
    readonly property real metadataTapHeightRatio: 0.24
    readonly property real overlayWidth: Math.min(root.width * 0.72, 760)
    readonly property int overlayRadius: 14
    readonly property color overlayColor: "#73232d3f"
    property string displayedImage: ""
    property bool metadataVisible: false
    property bool touchDebugSeen: false
    property int touchDebugX: 0
    property int touchDebugY: 0
    property string touchDebugPressText: "press: waiting"
    property string touchDebugClickText: "click: waiting"

    function uiIconSource(fileName) {
        if (useQrcAssets) {
            return "qrc:/assets/ui/" + fileName
        }
        return Qt.resolvedUrl("../assets/ui/" + fileName)
    }

    function startPhotoTransition() {
        if (fadeOut.running) {
            return
        }

        if (!fadeIn.running && root.backend.currentImage === root.displayedImage) {
            return
        }

        metadataHideTimer.stop()
        root.metadataVisible = false
        fadeIn.stop()
        fadeOut.start()
    }

    function showPhotoDetails() {
        if (root.backend.currentPhotoDetails.length === 0) {
            return
        }

        root.metadataVisible = true
        metadataHideTimer.restart()
    }

    function touchZone(x, y) {
        if (y < root.height * root.metadataTapHeightRatio
                && x > root.width * 0.18
                && x < root.width * 0.82) {
            return "metadata trigger"
        }

        return x < root.width * 0.50 ? "previous" : "next"
    }

    function correctedTouchPoint(rawX, rawY) {
        if (root.touchRotation === 180) {
            return Qt.point(root.width - rawX, root.height - rawY)
        }

        return Qt.point(rawX, rawY)
    }

    function pointInItem(item, x, y) {
        const origin = item.mapToItem(root, 0, 0)
        return x >= origin.x
            && x <= origin.x + item.width
            && y >= origin.y
            && y <= origin.y + item.height
    }

    function recordTouch(source, phase, rawX, rawY, routedZone) {
        if (!root.touchDebugEnabled) {
            return
        }

        const point = root.correctedTouchPoint(rawX, rawY)
        root.touchDebugSeen = true
        root.touchDebugX = Math.round(point.x)
        root.touchDebugY = Math.round(point.y)

        const line = phase + " " + source
            + " x=" + root.touchDebugX
            + " y=" + root.touchDebugY
            + (root.touchRotation === 180
                ? " raw=" + Math.round(rawX) + "," + Math.round(rawY)
                : "")
            + " size=" + Math.round(root.width) + "x" + Math.round(root.height)
            + " zone=" + root.touchZone(point.x, point.y)
            + (routedZone ? " routed=" + routedZone : "")

        if (phase === "press") {
            root.touchDebugPressText = line
        } else {
            root.touchDebugClickText = line
        }
        console.log("touch-debug " + line)
    }

    function routeCorrectedClick(rawX, rawY) {
        const point = root.correctedTouchPoint(rawX, rawY)

        if (statusPanel.visible && root.pointInItem(statusPanel, point.x, point.y)) {
            return "blocked status"
        }

        if (root.metadataVisible
                && root.backend.currentPhotoDetails.length > 0
                && root.pointInItem(metadataPanel, point.x, point.y)) {
            return "blocked metadata"
        }

        if (root.pointInItem(syncButton, point.x, point.y)) {
            if (root.backend.syncEnabled) {
                root.backend.syncNow()
            }
            return "sync"
        }

        if (root.pointInItem(shutdownButton, point.x, point.y)) {
            root.backend.shutdownNow()
            return "shutdown"
        }

        if (root.pointInItem(infoPanel, point.x, point.y)) {
            return "blocked info"
        }

        return root.routePhotoClick(point.x, point.y)
    }

    function routePhotoClick(x, y) {
        if (y < root.height * root.metadataTapHeightRatio
                && x > root.width * 0.18
                && x < root.width * 0.82) {
            root.showPhotoDetails()
            return "metadata trigger"
        }

        if (x < root.width * 0.50) {
            root.previousPhoto()
            return "previous"
        }

        root.nextPhoto()
        return "next"
    }

    function navigationLocked() {
        return fadeOut.running || fadeIn.running
    }

    function previousPhoto() {
        if (!navigationLocked()) {
            root.backend.previousImage()
        }
    }

    function nextPhoto() {
        if (!navigationLocked()) {
            root.backend.nextImage()
        }
    }

    Image {
        id: photo
        anchors.fill: parent
        source: root.displayedImage
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        retainWhileLoading: false
        sourceSize.width: Math.max(1, root.width)
        sourceSize.height: Math.max(1, root.height)
        opacity: 1.0
        z: -1

        Component.onCompleted: {
            root.displayedImage = root.backend.currentImage
            opacity = root.displayedImage ? 1.0 : 0.0
        }
    }

    Connections {
        target: root.backend

        function onCurrentImageChanged() {
            root.startPhotoTransition()
        }
    }

    Timer {
        id: metadataHideTimer
        interval: 8000
        repeat: false
        onTriggered: root.metadataVisible = false
    }

    NumberAnimation {
        id: fadeOut
        target: photo
        property: "opacity"
        to: 0.0
        duration: 350
        easing.type: Easing.InOutQuad
        onFinished: {
            root.displayedImage = root.backend.currentImage
            if (root.displayedImage) {
                fadeIn.start()
            }
        }
    }

    NumberAnimation {
        id: fadeIn
        target: photo
        property: "opacity"
        to: 1.0
        duration: 500
        easing.type: Easing.InOutQuad
    }

    Rectangle {
        anchors.fill: parent
        color: "#10151f"
        visible: !root.backend.hasImages
        z: -2
    }

    Text {
        anchors.centerIn: parent
        visible: !root.backend.hasImages
        text: "No local photos yet"
        color: "#d8e4f2"
        font.pixelSize: 38
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        enabled: root.touchRotation === 0
        z: -0.5

        onPressed: (mouse) => {
            root.recordTouch("photo", "press", mouse.x, mouse.y, "")
        }

        onClicked: (mouse) => {
            const routedZone = root.routePhotoClick(mouse.x, mouse.y)
            root.recordTouch("photo", "click", mouse.x, mouse.y, routedZone)
        }
    }

    Rectangle {
        id: statusPanel
        width: root.overlayWidth
        height: 50
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 14
        radius: root.overlayRadius
        color: root.overlayColor
        visible: root.backend.syncStatus.length > 0
        z: 2

        Text {
            anchors.centerIn: parent
            text: root.backend.syncStatus
            color: "#e7f1ff"
            font.pixelSize: 19
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            enabled: root.touchRotation === 0

            onPressed: (mouse) => {
                const point = statusPanel.mapToItem(root, mouse.x, mouse.y)
                root.recordTouch("status", "press", point.x, point.y, "")
            }

            onClicked: (mouse) => {
                const point = statusPanel.mapToItem(root, mouse.x, mouse.y)
                root.recordTouch("status", "click", point.x, point.y, "blocked status")
            }
        }
    }

    Rectangle {
        id: metadataPanel
        width: root.overlayWidth
        height: Math.min(metadataText.implicitHeight + 30, root.height * 0.36)
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: statusPanel.visible ? 78 : 18
        radius: root.overlayRadius
        color: root.overlayColor
        clip: true
        opacity: root.metadataVisible && root.backend.currentPhotoDetails.length > 0 ? 1 : 0
        z: 1

        Behavior on opacity {
            NumberAnimation {
                duration: 180
                easing.type: Easing.InOutQuad
            }
        }

        Text {
            id: metadataText
            anchors.fill: parent
            anchors.margins: 15
            text: root.backend.currentPhotoDetails
            color: "#f5fbff"
            font.pixelSize: root.isPortrait ? 23 : 21
            lineHeight: 1.12
            wrapMode: Text.WordWrap
            elide: Text.ElideRight
        }

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            enabled: root.touchRotation === 0
                && root.metadataVisible
                && root.backend.currentPhotoDetails.length > 0

            onPressed: (mouse) => {
                const point = metadataPanel.mapToItem(root, mouse.x, mouse.y)
                root.recordTouch("metadata panel", "press", point.x, point.y, "")
            }

            onClicked: (mouse) => {
                const point = metadataPanel.mapToItem(root, mouse.x, mouse.y)
                root.recordTouch("metadata panel", "click", point.x, point.y, "blocked metadata")
            }
        }
    }

    Rectangle {
        id: infoPanel
        width: root.isPortrait ? Math.min(root.width * 0.88, 700) : Math.min(root.width * 0.60, 520)
        height: root.isPortrait ? 220 : 166
        anchors.horizontalCenter: root.isPortrait ? parent.horizontalCenter : undefined
        anchors.left: root.isPortrait ? undefined : parent.left
        anchors.leftMargin: root.isPortrait ? 0 : 20
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root.isPortrait ? 24 : 14
        radius: 16
        color: "#6f0c1320"

        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton
            enabled: root.touchRotation === 0

            onPressed: (mouse) => {
                const point = infoPanel.mapToItem(root, mouse.x, mouse.y)
                root.recordTouch("info panel", "press", point.x, point.y, "")
            }

            onClicked: (mouse) => {
                const point = infoPanel.mapToItem(root, mouse.x, mouse.y)
                root.recordTouch("info panel", "click", point.x, point.y, "blocked info")
            }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: root.isPortrait ? 3 : 1

            Text {
                text: root.backend.clockText
                color: "#ffffff"
                font.pixelSize: root.isPortrait ? 68 : 56
                font.bold: true
            }

            Text {
                text: root.backend.dateText
                color: "#d4deea"
                Layout.topMargin: -6
                font.pixelSize: root.isPortrait ? 26 : 21
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: root.isPortrait ? 8 : 10

                VectorImage {
                    source: root.backend.weatherIcon
                    Layout.preferredWidth: root.isPortrait ? 38 : 40
                    Layout.preferredHeight: root.isPortrait ? 38 : 40
                    fillMode: VectorImage.PreserveAspectFit
                }

                Text {
                    Layout.fillWidth: true
                    text: root.backend.weatherText
                    color: "#ecf6ff"
                    font.pixelSize: root.isPortrait ? 28 : 24
                    elide: Text.ElideRight
                }

                BusyIndicator {
                    running: root.backend.syncInProgress
                    visible: running
                    implicitWidth: root.actionBusySize
                    implicitHeight: root.actionBusySize
                }

                ToolButton {
                    id: syncButton
                    Layout.preferredWidth: root.actionButtonSize
                    Layout.preferredHeight: root.actionButtonSize
                    padding: 0
                    display: AbstractButton.IconOnly
                    icon.source: root.uiIconSource("sync.svg")
                    icon.width: root.actionIconSize
                    icon.height: root.actionIconSize
                    icon.color: "#ffffff"
                    enabled: root.backend.syncEnabled
                    opacity: enabled ? 1.0 : 0.45
                    onPressedChanged: {
                        if (pressed) {
                            const point = syncButton.mapToItem(root, syncButton.width / 2, syncButton.height / 2)
                            root.recordTouch("sync button", "press", point.x, point.y, "")
                        }
                    }
                    onClicked: {
                        const point = syncButton.mapToItem(root, syncButton.width / 2, syncButton.height / 2)
                        root.recordTouch("sync button", "click", point.x, point.y, "sync")
                        root.backend.syncNow()
                    }

                    background: Rectangle {
                        radius: width / 2
                        color: syncButton.down ? "#d8263948" : "#9d162432"
                        border.width: root.isPortrait ? 1.3 : 1
                        border.color: syncButton.enabled
                            ? (root.isPortrait ? "#9ce6f7ff" : "#69d6e8ff")
                            : "#3d7f95a6"
                    }
                }

                ToolButton {
                    id: shutdownButton
                    Layout.preferredWidth: root.actionButtonSize
                    Layout.preferredHeight: root.actionButtonSize
                    padding: 0
                    display: AbstractButton.IconOnly
                    icon.source: root.uiIconSource("shutdown.svg")
                    icon.width: root.actionIconSize
                    icon.height: root.actionIconSize
                    icon.color: "#ffffff"
                    onPressedChanged: {
                        if (pressed) {
                            const point = shutdownButton.mapToItem(root, shutdownButton.width / 2, shutdownButton.height / 2)
                            root.recordTouch("shutdown button", "press", point.x, point.y, "")
                        }
                    }
                    onClicked: {
                        const point = shutdownButton.mapToItem(root, shutdownButton.width / 2, shutdownButton.height / 2)
                        root.recordTouch("shutdown button", "click", point.x, point.y, "shutdown")
                        root.backend.shutdownNow()
                    }

                    background: Rectangle {
                        radius: width / 2
                        color: shutdownButton.down ? "#df463747" : "#af2a1f34"
                        border.width: root.isPortrait ? 1.3 : 1
                        border.color: root.isPortrait ? "#ffd1c8" : "#f5bbb0"
                    }
                }
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        enabled: root.touchRotation === 180
        z: 90

        onPressed: (mouse) => {
            root.recordTouch("corrected touch", "press", mouse.x, mouse.y, "")
        }

        onClicked: (mouse) => {
            const routedZone = root.routeCorrectedClick(mouse.x, mouse.y)
            root.recordTouch("corrected touch", "click", mouse.x, mouse.y, routedZone)
        }
    }

    Rectangle {
        id: touchDebugPanel
        visible: root.touchDebugEnabled
        width: Math.min(root.width - 24, 760)
        height: 88
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 10
        radius: 8
        color: "#df111722"
        border.width: 1
        border.color: "#f5ffffff"
        z: 100

        Text {
            anchors.fill: parent
            anchors.margins: 10
            text: root.touchDebugPressText + "\n" + root.touchDebugClickText
            color: "#ffffff"
            font.pixelSize: 16
            font.bold: true
            wrapMode: Text.WordWrap
        }
    }

    Rectangle {
        visible: root.touchDebugEnabled && root.touchDebugSeen
        width: 28
        height: 28
        radius: 14
        x: Math.max(0, Math.min(root.width - width, root.touchDebugX - width / 2))
        y: Math.max(0, Math.min(root.height - height, root.touchDebugY - height / 2))
        color: "#f4ff3355"
        border.width: 3
        border.color: "#ffffff"
        z: 101
    }
}
