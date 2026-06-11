import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.VectorImage

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
    property int displayedImageWidth: 0
    property int displayedImageHeight: 0
    property bool displayedImageHasFaceBounds: false
    property real displayedImageFaceX1: 0
    property real displayedImageFaceY1: 0
    property real displayedImageFaceX2: 0
    property real displayedImageFaceY2: 0
    property bool controlsVisible: false
    property bool metadataVisible: false

    function updateDisplayedImageState() {
        root.displayedImage = root.backend.currentImage
        root.displayedImageWidth = root.backend.currentImageWidth
        root.displayedImageHeight = root.backend.currentImageHeight
        root.displayedImageHasFaceBounds = root.backend.currentImageHasFaceBounds
        root.displayedImageFaceX1 = root.backend.currentImageFaceX1
        root.displayedImageFaceY1 = root.backend.currentImageFaceY1
        root.displayedImageFaceX2 = root.backend.currentImageFaceX2
        root.displayedImageFaceY2 = root.backend.currentImageFaceY2
    }

    function photoHorizontalAlignment() {
        if (!root.displayedImageHasFaceBounds || root.displayedImageWidth <= 0
                || root.displayedImageHeight <= 0 || root.width <= 0 || root.height <= 0) {
            return Image.AlignHCenter
        }

        var imageAspect = root.displayedImageWidth / root.displayedImageHeight
        var targetAspect = root.width / root.height
        if (imageAspect <= targetAspect) {
            return Image.AlignHCenter
        }

        var visibleWidth = targetAspect / imageAspect
        var centerCropLeft = (1.0 - visibleWidth) / 2.0
        var centerCropRight = centerCropLeft + visibleWidth
        var padding = Math.min(0.08, Math.max(0.035, (root.displayedImageFaceX2 - root.displayedImageFaceX1) * 0.32))
        if (root.displayedImageFaceX1 < centerCropLeft + padding) {
            return Image.AlignLeft
        }
        if (root.displayedImageFaceX2 > centerCropRight - padding) {
            return Image.AlignRight
        }
        return Image.AlignHCenter
    }

    function photoVerticalAlignment() {
        if (!root.displayedImageHasFaceBounds || root.displayedImageWidth <= 0
                || root.displayedImageHeight <= 0 || root.width <= 0 || root.height <= 0) {
            return Image.AlignVCenter
        }

        var imageAspect = root.displayedImageWidth / root.displayedImageHeight
        var targetAspect = root.width / root.height
        if (imageAspect >= targetAspect) {
            return Image.AlignVCenter
        }

        var visibleHeight = imageAspect / targetAspect
        var centerCropTop = (1.0 - visibleHeight) / 2.0
        var centerCropBottom = centerCropTop + visibleHeight
        var padding = Math.min(0.08, Math.max(0.035, (root.displayedImageFaceY2 - root.displayedImageFaceY1) * 0.32))
        if (root.displayedImageFaceY1 < centerCropTop + padding) {
            return Image.AlignTop
        }
        if (root.displayedImageFaceY2 > centerCropBottom - padding) {
            return Image.AlignBottom
        }
        return Image.AlignVCenter
    }

    function weatherTemperatureText() {
        var weatherText = root.backend.weatherText
        var legacyMatch = weatherText.match(/^(-?\d+)\s*[FC]\s*\|\s*(.+)$/)
        if (legacyMatch) {
            return legacyMatch[1] + "°"
        }

        var degreeMatch = weatherText.match(/^(-?\d+°)\s+(.+)$/)
        if (degreeMatch) {
            return degreeMatch[1]
        }

        return ""
    }

    function weatherConditionText() {
        var weatherText = root.backend.weatherText
        var legacyMatch = weatherText.match(/^(-?\d+)\s*[FC]\s*\|\s*(.+)$/)
        if (legacyMatch) {
            return legacyMatch[2]
        }

        var degreeMatch = weatherText.match(/^(-?\d+°)\s+(.+)$/)
        if (degreeMatch) {
            return degreeMatch[2]
        }

        return weatherText
    }

    function metadataLines() {
        var rawLines = root.backend.currentPhotoDetails.split("\n")
        var lines = []
        for (var index = 0; index < rawLines.length; index += 1) {
            var line = rawLines[index].trim()
            if (line.length > 0) {
                lines.push(line)
            }
        }
        return lines
    }

    function metadataTitleText() {
        var lines = root.metadataLines()
        return lines.length > 0 ? lines[0] : ""
    }

    function metadataBodyText() {
        var lines = root.metadataLines()
        return lines.length > 1 ? lines.slice(1).join("\n") : ""
    }

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

    function revealControls() {
        root.controlsVisible = true
        controlsHideTimer.restart()
    }

    Image {
        id: photo
        anchors.fill: parent
        source: root.displayedImage
        fillMode: Image.PreserveAspectCrop
        horizontalAlignment: root.photoHorizontalAlignment()
        verticalAlignment: root.photoVerticalAlignment()
        asynchronous: true
        cache: false
        retainWhileLoading: false
        sourceSize.width: Math.max(1, root.width)
        sourceSize.height: Math.max(1, root.height)
        opacity: 1.0
        z: -1

        Component.onCompleted: {
            root.updateDisplayedImageState()
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

    Timer {
        id: controlsHideTimer
        interval: 6500
        repeat: false
        onTriggered: {
            if (!root.backend.syncInProgress && !shutdownHoldTimer.running) {
                root.controlsVisible = false
            } else {
                restart()
            }
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
            root.updateDisplayedImageState()
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

    Item {
        id: metadataCaption
        width: root.isPortrait ? Math.min(root.width * 0.84, 620) : Math.min(root.width * 0.38, 460)
        height: metadataColumn.implicitHeight
        anchors.horizontalCenter: root.isPortrait ? parent.horizontalCenter : undefined
        anchors.right: root.isPortrait ? undefined : parent.right
        anchors.rightMargin: root.isPortrait ? 0 : 36
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root.isPortrait ? 270 : 34
        opacity: root.metadataVisible && root.backend.currentPhotoDetails.length > 0 ? 1 : 0
        visible: opacity > 0.01
        z: 2

        Behavior on opacity {
            NumberAnimation {
                duration: 220
                easing.type: Easing.InOutQuad
            }
        }

        ColumnLayout {
            id: metadataColumn
            width: parent.width
            spacing: root.isPortrait ? 7 : 6

            Text {
                Layout.fillWidth: true
                horizontalAlignment: root.isPortrait ? Text.AlignHCenter : Text.AlignRight
                text: root.metadataTitleText()
                color: "#ffffff"
                font.pixelSize: root.isPortrait ? 25 : 24
                font.weight: Font.DemiBold
                maximumLineCount: 1
                elide: Text.ElideRight
                style: Text.Raised
                styleColor: "#a0000000"
            }

            Text {
                Layout.fillWidth: true
                horizontalAlignment: root.isPortrait ? Text.AlignHCenter : Text.AlignRight
                text: root.metadataBodyText()
                visible: text.length > 0
                color: "#e1eaf4"
                font.pixelSize: root.isPortrait ? 19 : 18
                font.weight: Font.Normal
                lineHeight: 1.12
                maximumLineCount: root.isPortrait ? 5 : 6
                wrapMode: Text.WordWrap
                elide: Text.ElideRight
                style: Text.Raised
                styleColor: "#99000000"
            }
        }
    }

    Rectangle {
        id: bottomScrim
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: root.isPortrait ? Math.min(root.height * 0.46, 420) : Math.min(root.height * 0.40, 300)
        z: 0
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: "#00000000" }
            GradientStop { position: 0.48; color: "#3d000000" }
            GradientStop { position: 1.0; color: "#b8000000" }
        }
    }

    Item {
        id: infoPanel
        width: root.isPortrait ? Math.min(root.width * 0.88, 700) : Math.min(root.width * 0.60, 520)
        height: root.isPortrait ? 220 : 166
        anchors.horizontalCenter: root.isPortrait ? parent.horizontalCenter : undefined
        anchors.left: root.isPortrait ? undefined : parent.left
        anchors.leftMargin: root.isPortrait ? 0 : 34
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root.isPortrait ? 30 : 26
        z: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 0
            spacing: root.isPortrait ? 3 : 1

            Text {
                text: root.backend.clockText
                color: "#ffffff"
                font.pixelSize: root.isPortrait ? 68 : 56
                font.weight: Font.DemiBold
                style: Text.Raised
                styleColor: "#8a000000"
            }

            Text {
                text: root.backend.dateText
                color: "#d4deea"
                Layout.topMargin: -6
                font.pixelSize: root.isPortrait ? 26 : 21
                style: Text.Raised
                styleColor: "#85000000"
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: root.isPortrait ? 6 : 4
                spacing: root.isPortrait ? 10 : 12

                VectorImage {
                    source: root.backend.weatherIcon
                    Layout.preferredWidth: root.isPortrait ? 34 : 36
                    Layout.preferredHeight: root.isPortrait ? 34 : 36
                    Layout.alignment: Qt.AlignVCenter
                    fillMode: VectorImage.PreserveAspectFit
                    animations.loops: Animation.Infinite
                }

                Text {
                    text: root.weatherTemperatureText()
                    color: "#ffffff"
                    visible: text.length > 0
                    font.pixelSize: root.isPortrait ? 31 : 27
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                    style: Text.Raised
                    styleColor: "#85000000"
                }

                Text {
                    Layout.fillWidth: true
                    text: root.weatherConditionText()
                    color: "#e5edf6"
                    font.pixelSize: root.isPortrait ? 25 : 22
                    font.weight: Font.Normal
                    elide: Text.ElideRight
                    style: Text.Raised
                    styleColor: "#85000000"
                }

                BusyIndicator {
                    running: root.backend.syncInProgress
                    visible: true
                    opacity: running ? 1.0 : 0.0
                    implicitWidth: root.actionBusySize
                    implicitHeight: root.actionBusySize
                }

                RowLayout {
                    id: actionControls
                    spacing: root.isPortrait ? 8 : 7
                    visible: true
                    opacity: root.controlsVisible || root.backend.syncInProgress ? 1.0 : 0.0
                    enabled: opacity > 0.7

                    Behavior on opacity {
                        NumberAnimation {
                            duration: 180
                            easing.type: Easing.InOutQuad
                        }
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
                        onClicked: {
                            root.revealControls()
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
                        opacity: pressed ? 1.0 : 0.82
                        onPressedChanged: {
                            if (pressed) {
                                root.revealControls()
                                shutdownHoldTimer.restart()
                            } else {
                                shutdownHoldTimer.stop()
                            }
                        }

                        Timer {
                            id: shutdownHoldTimer
                            interval: 1100
                            repeat: false
                            onTriggered: {
                                root.controlsVisible = false
                                root.backend.shutdownNow()
                            }
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
    }
}
