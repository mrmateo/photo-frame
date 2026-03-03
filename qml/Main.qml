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
    title: "Photo Frame - PySide6 + Qt Quick"

    readonly property bool isPortrait: root.height >= root.width
    readonly property bool useQrcAssets: root.backend.weatherIcon.indexOf("qrc:/") === 0
    readonly property int actionButtonSize: root.isPortrait ? 50 : 42
    readonly property int actionIconSize: root.isPortrait ? 24 : 20
    readonly property int actionBusySize: root.isPortrait ? 28 : 24
    property string displayedImage: ""

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

        fadeIn.stop()
        fadeOut.start()
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
                    icon.color: "#ffffff"
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
                    icon.color: "#ffffff"
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
