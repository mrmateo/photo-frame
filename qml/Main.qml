import QtQuick

Window {
    id: root
    required property var backend
    required property bool startFullScreen
    required property int initialWindowWidth
    required property int initialWindowHeight

    width: root.initialWindowWidth
    height: root.initialWindowHeight
    visible: true
    visibility: root.startFullScreen ? Window.FullScreen : Window.Windowed
    color: "#000000"
    title: "Photo Frame - PySide6 + Qt Quick"

    readonly property real metadataTapHeightRatio: 0.24
    readonly property real overlayWidth: Math.min(root.width * 0.72, 760)
    readonly property int overlayRadius: 14
    readonly property color overlayColor: "#73232d3f"
    readonly property string displayedImage: slideshow.displayedImage
    readonly property var displayedCropInfo: slideshow.displayedCropInfo
    readonly property bool photoTransitionRunning: slideshow.photoTransitionRunning
    property bool controlsVisible: false
    property bool metadataVisible: false

    function showPhotoDetails() {
        if (root.backend.currentPhotoDetails.length === 0
                || root.backend.currentImage !== root.displayedImage || slideshow.photoTransitionRunning) {
            return
        }

        root.metadataVisible = true
        metadataHideTimer.restart()
    }

    function revealControls() {
        root.controlsVisible = true
        controlsHideTimer.restart()
    }

    Slideshow {
        id: slideshow
        anchors.fill: parent
        z: -1
        backend: root.backend
        onPhotoRequested: {
            metadataHideTimer.stop()
            root.metadataVisible = false
        }
    }

    InfoPanel {
        id: infoPanel
        anchors.fill: parent
        z: 1
        backend: root.backend
        controlsVisible: root.controlsVisible
        metadataVisible: root.metadataVisible
        onControlsRequested: root.revealControls()
        onShutdownRequested: {
            root.controlsVisible = false
            root.backend.shutdownNow()
        }
    }

    Timer {
        id: metadataHideTimer
        interval: 8000
        repeat: false
        onTriggered: root.metadataVisible = false
    }

    Timer {
        id: controlsHideTimer
        interval: 6500
        repeat: false
        onTriggered: {
            if (!root.backend.syncInProgress && !infoPanel.shutdownHolding) {
                root.controlsVisible = false
            } else {
                restart()
            }
        }
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

    TapHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchScreen | PointerDevice.TouchPad
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: (eventPoint) => {
            if (eventPoint.position.y < root.height * root.metadataTapHeightRatio
                    && eventPoint.position.x > root.width * 0.18
                    && eventPoint.position.x < root.width * 0.82) {
                root.showPhotoDetails()
                root.revealControls()
            } else if (eventPoint.position.x < root.width * 0.40) {
                root.backend.previousImage()
            } else if (eventPoint.position.x > root.width * 0.60) {
                root.backend.nextImage()
            } else {
                root.revealControls()
            }
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
    }

}
