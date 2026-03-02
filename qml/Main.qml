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

    Image {
        id: photo
        anchors.fill: parent
        source: root.backend.currentImage
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
        retainWhileLoading: true
        sourceSize.width: Math.max(1, root.width)
        sourceSize.height: Math.max(1, root.height)
        opacity: 1.0
        z: -1

        onSourceChanged: {
            opacity = 0.0
            fadeIn.restart()
        }

        NumberAnimation {
            id: fadeIn
            target: photo
            property: "opacity"
            from: 0.0
            to: 1.0
            duration: 850
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
        width: root.isPortrait ? Math.min(root.width * 0.92, 760) : Math.min(root.width * 0.66, 560)
        height: root.isPortrait ? 250 : 190
        anchors.horizontalCenter: root.isPortrait ? parent.horizontalCenter : undefined
        anchors.left: root.isPortrait ? undefined : parent.left
        anchors.leftMargin: root.isPortrait ? 0 : 24
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root.isPortrait ? 26 : 18
        radius: 18
        color: "#7a0d1422"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 8

            Text {
                text: root.backend.clockText
                color: "#ffffff"
                font.pixelSize: root.isPortrait ? 74 : 62
                font.bold: true
            }

            Text {
                text: root.backend.dateText
                color: "#d4deea"
                font.pixelSize: root.isPortrait ? 30 : 24
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                Image {
                    source: root.backend.weatherIcon
                    Layout.preferredWidth: 42
                    Layout.preferredHeight: 42
                    fillMode: Image.PreserveAspectFit
                }

                Text {
                    Layout.fillWidth: true
                    text: root.backend.weatherText
                    color: "#ecf6ff"
                    font.pixelSize: root.isPortrait ? 34 : 28
                    elide: Text.ElideRight
                }

                BusyIndicator {
                    running: root.backend.syncInProgress
                    visible: running
                    implicitWidth: 34
                    implicitHeight: 34
                }

                Button {
                    text: "Sync"
                    enabled: root.backend.syncEnabled
                    onClicked: root.backend.syncNow()
                }

                Button {
                    text: "Shutdown"
                    onClicked: root.backend.shutdownNow()
                }
            }
        }
    }
}
