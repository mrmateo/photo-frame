import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Window {
    id: root
    required property var backend

    width: 1280
    height: 720
    visible: true
    visibility: Window.FullScreen
    color: "#000000"
    title: "Photo Frame"

    readonly property bool isPortrait: root.height >= root.width
    readonly property bool useQrcAssets: root.backend.weatherIcon.indexOf("qrc:/") === 0
    readonly property int actionButtonSize: root.isPortrait ? 50 : 42
    readonly property int actionIconSize: root.isPortrait ? 22 : 18
    readonly property int actionBusySize: root.isPortrait ? 28 : 24

    property bool primaryPhotoActive: true
    property string pendingPhotoSource: ""
    property bool photoTransitionRunning: false

    function activePhoto() {
        return primaryPhotoActive ? photoPrimary : photoSecondary
    }

    function inactivePhoto() {
        return primaryPhotoActive ? photoSecondary : photoPrimary
    }

    function uiIconSource(fileName) {
        if (useQrcAssets) {
            return "qrc:/assets/ui/" + fileName
        }
        return Qt.resolvedUrl("../assets/ui/" + fileName)
    }

    function queuePhotoSource(nextSource) {
        if (!nextSource || nextSource.length === 0) {
            pendingPhotoSource = ""
            photoTransitionRunning = false
            crossFade.stop()
            photoPrimary.source = ""
            photoSecondary.source = ""
            photoPrimary.opacity = 0
            photoSecondary.opacity = 0
            return
        }

        const currentPhoto = activePhoto()
        if (currentPhoto.source === nextSource && currentPhoto.opacity > 0.99) {
            pendingPhotoSource = ""
            return
        }

        pendingPhotoSource = nextSource
        loadPendingPhoto()
    }

    function loadPendingPhoto() {
        if (photoTransitionRunning || pendingPhotoSource.length === 0) {
            return
        }

        const currentPhoto = activePhoto()
        const nextPhoto = inactivePhoto()

        if (nextPhoto.source !== pendingPhotoSource) {
            nextPhoto.opacity = 0
            nextPhoto.source = pendingPhotoSource
        }

        if (nextPhoto.status === Image.Ready) {
            if (!currentPhoto.source || currentPhoto.opacity <= 0.01) {
                swapPhotoImmediately(nextPhoto)
            } else {
                startPhotoCrossFade()
            }
        } else if (nextPhoto.status === Image.Error) {
            pendingPhotoSource = ""
        }
    }

    function handlePhotoStatusChanged(photoItem) {
        const nextPhoto = inactivePhoto()
        if (photoItem !== nextPhoto || photoTransitionRunning || pendingPhotoSource.length === 0) {
            return
        }
        if (photoItem.source !== pendingPhotoSource) {
            return
        }

        if (photoItem.status === Image.Ready) {
            if (!activePhoto().source || activePhoto().opacity <= 0.01) {
                swapPhotoImmediately(photoItem)
            } else {
                startPhotoCrossFade()
            }
        } else if (photoItem.status === Image.Error) {
            pendingPhotoSource = ""
        }
    }

    function swapPhotoImmediately(readyPhoto) {
        const otherPhoto = readyPhoto === photoPrimary ? photoSecondary : photoPrimary
        readyPhoto.opacity = 1
        otherPhoto.opacity = 0
        primaryPhotoActive = readyPhoto === photoPrimary
        pendingPhotoSource = ""
    }

    function startPhotoCrossFade() {
        const currentPhoto = activePhoto()
        const nextPhoto = inactivePhoto()

        if (nextPhoto.status !== Image.Ready || pendingPhotoSource.length === 0) {
            return
        }

        photoTransitionRunning = true
        fadeOutAnimation.target = currentPhoto
        fadeOutAnimation.from = currentPhoto.opacity
        fadeOutAnimation.to = 0.0
        fadeInAnimation.target = nextPhoto
        fadeInAnimation.from = nextPhoto.opacity
        fadeInAnimation.to = 1.0
        pendingPhotoSource = ""
        crossFade.restart()
    }

    Connections {
        target: root.backend

        function onCurrentImageChanged() {
            root.queuePhotoSource(root.backend.currentImage)
        }
    }

    Component.onCompleted: root.queuePhotoSource(root.backend.currentImage)

    Image {
        id: photoPrimary
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        retainWhileLoading: true
        sourceSize.width: Math.max(1, root.width)
        sourceSize.height: Math.max(1, root.height)
        opacity: 0
        z: root.primaryPhotoActive ? -1 : -2

        onStatusChanged: root.handlePhotoStatusChanged(photoPrimary)
    }

    Image {
        id: photoSecondary
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        retainWhileLoading: true
        sourceSize.width: Math.max(1, root.width)
        sourceSize.height: Math.max(1, root.height)
        opacity: 0
        z: root.primaryPhotoActive ? -2 : -1

        onStatusChanged: root.handlePhotoStatusChanged(photoSecondary)
    }

    ParallelAnimation {
        id: crossFade
        running: false

        NumberAnimation {
            id: fadeOutAnimation
            property: "opacity"
            duration: 620
            easing.type: Easing.InOutQuad
        }

        NumberAnimation {
            id: fadeInAnimation
            property: "opacity"
            duration: 620
            easing.type: Easing.InOutQuad
        }

        onFinished: {
            root.primaryPhotoActive = fadeInAnimation.target === photoPrimary
            root.photoTransitionRunning = false
            root.loadPendingPhoto()
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
            if (eventPoint.position.x < root.width * 0.40) {
                root.backend.previousImage()
            } else if (eventPoint.position.x > root.width * 0.60) {
                root.backend.nextImage()
            }
        }
    }

    Rectangle {
        id: statusPanel
        width: Math.min(root.width * 0.72, 760)
        height: 50
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: 14
        radius: 14
        color: "#73232d3f"
        visible: root.backend.syncStatus.length > 0
        opacity: visible ? 1 : 0

        Text {
            anchors.centerIn: parent
            text: root.backend.syncStatus
            color: "#e7f1ff"
            font.pixelSize: 19
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

                Image {
                    source: root.backend.weatherIcon
                    Layout.preferredWidth: root.isPortrait ? 38 : 40
                    Layout.preferredHeight: root.isPortrait ? 38 : 40
                    fillMode: Image.PreserveAspectFit
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
                    enabled: root.backend.syncEnabled
                    opacity: enabled ? 1.0 : 0.45
                    onClicked: root.backend.syncNow()

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
                    onClicked: root.backend.shutdownNow()

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
}
