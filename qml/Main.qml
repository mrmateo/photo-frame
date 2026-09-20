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
    property var activePhotoLayer: photoLayerA
    readonly property var incomingPhotoLayer: activePhotoLayer === photoLayerA ? photoLayerB : photoLayerA
    readonly property string displayedImage: activePhotoLayer.imageSource
    readonly property var displayedCropInfo: activePhotoLayer.cropInfo
    readonly property bool photoTransitionRunning: crossFade.running
    property bool photoLayersReady: false
    property bool controlsVisible: false
    property bool metadataVisible: false

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
        if (!root.photoLayersReady) {
            return
        }

        metadataHideTimer.stop()
        root.metadataVisible = false

        if (!root.backend.currentImage) {
            crossFade.stop()
            photoLayerA.clear()
            photoLayerB.clear()
            return
        }

        // Finish an in-flight dissolve before loading the latest requested photo.
        // Rapid taps therefore never replace either of the visible image layers.
        if (crossFade.running) {
            return
        }

        var incoming = root.incomingPhotoLayer
        if (root.backend.currentImage === root.displayedImage) {
            incoming.clear()
            return
        }

        incoming.opacity = 0
        incoming.cropInfo = root.backend.currentCropInfo
        incoming.imageSource = root.backend.currentImage
        root.tryPhotoTransition()
    }

    function tryPhotoTransition() {
        var incoming = root.incomingPhotoLayer
        if (!root.photoLayersReady || crossFade.running || !incoming.imageSource
                || incoming.imageSource !== root.backend.currentImage || !incoming.ready) {
            return
        }

        if (!root.displayedImage) {
            // The first photo can appear as soon as it has decoded.
            root.finishPhotoTransition()
        } else {
            crossFade.start()
        }
    }

    function finishPhotoTransition() {
        var outgoing = root.activePhotoLayer
        var incoming = root.incomingPhotoLayer
        incoming.opacity = 1
        root.activePhotoLayer = incoming
        outgoing.clear()
        if (root.backend.currentImage !== root.displayedImage) {
            Qt.callLater(root.startPhotoTransition)
        }
    }

    function showPhotoDetails() {
        if (root.backend.currentPhotoDetails.length === 0
                || root.backend.currentImage !== root.displayedImage || crossFade.running) {
            return
        }

        root.metadataVisible = true
        metadataHideTimer.restart()
    }

    function revealControls() {
        root.controlsVisible = true
        controlsHideTimer.restart()
    }

    function clamp(value, minimum, maximum) {
        return Math.max(minimum, Math.min(maximum, value))
    }

    function cropAxis(faceStart, faceEnd, cropLength) {
        var centeredStart = ((faceStart + faceEnd) / 2.0) - (cropLength / 2.0)
        var groupLength = faceEnd - faceStart

        if (groupLength <= cropLength) {
            // Keep every face inside the crop when geometry makes that possible.
            var minimumStart = faceEnd - cropLength
            var maximumStart = faceStart
            centeredStart = root.clamp(centeredStart, minimumStart, maximumStart)
        }

        return root.clamp(centeredStart, 0.0, 1.0 - cropLength)
    }

    function showWholeImage(bounds) {
        if (!bounds || bounds.left === undefined || root.width <= 0 || root.height <= 0) {
            return false
        }
        if (bounds.fit_only) {
            return true
        }
        var imageRatio = bounds.image_width / bounds.image_height
        var viewportRatio = root.width / root.height
        // Fit the entire photo when filling the viewport would cut any faces.
        return (bounds.right - bounds.left) > Math.min(1.0, viewportRatio / imageRatio) + 0.000001
                || (bounds.bottom - bounds.top) > Math.min(1.0, imageRatio / viewportRatio) + 0.000001
    }

    function smartCropRect(bounds) {
        if (!bounds || bounds.left === undefined || root.width <= 0 || root.height <= 0 || root.showWholeImage(bounds)) {
            return Qt.rect(0, 0, 0, 0)
        }

        var originalWidth = bounds.image_width
        var originalHeight = bounds.image_height
        if (originalWidth <= 0 || originalHeight <= 0) {
            return Qt.rect(0, 0, 0, 0)
        }

        var viewportRatio = root.width / root.height
        var imageRatio = originalWidth / originalHeight
        var imageWidth = imageRatio > viewportRatio ? root.height * imageRatio : root.width
        var imageHeight = imageRatio > viewportRatio ? root.height : root.width / imageRatio
        var cropLeft = 0.0
        var cropTop = 0.0
        var cropWidth = 1.0
        var cropHeight = 1.0

        if (imageRatio > viewportRatio) {
            cropWidth = viewportRatio / imageRatio
            cropLeft = root.cropAxis(bounds.left, bounds.right, cropWidth)
        } else if (imageRatio < viewportRatio) {
            cropHeight = imageRatio / viewportRatio
            cropTop = root.cropAxis(bounds.top, bounds.bottom, cropHeight)
        }

        return Qt.rect(
            cropLeft * imageWidth,
            cropTop * imageHeight,
            cropWidth * imageWidth,
            cropHeight * imageHeight
        )
    }

    function smartSourceWidth(bounds) {
        if (!bounds || !bounds.image_width || !bounds.image_height || root.showWholeImage(bounds)) {
            return Math.max(1, root.width)
        }
        var imageRatio = bounds.image_width / bounds.image_height
        var viewportRatio = root.width / root.height
        return Math.max(1, imageRatio > viewportRatio ? root.height * imageRatio : root.width)
    }

    function smartSourceHeight(bounds) {
        if (!bounds || !bounds.image_width || !bounds.image_height || root.showWholeImage(bounds)) {
            return Math.max(1, root.height)
        }
        var imageRatio = bounds.image_width / bounds.image_height
        var viewportRatio = root.width / root.height
        return Math.max(1, imageRatio > viewportRatio ? root.height : root.width / imageRatio)
    }

    component PhotoLayer: Rectangle {
        id: layer
        property string imageSource: ""
        property var cropInfo: ({})
        readonly property bool ready: photo.status === Image.Ready
        anchors.fill: parent
        clip: true
        // Include the matte in the dissolve so fitted photos do not leave the
        // outgoing image visible in their letterbox area.
        color: "#000000"
        // Composite photo and matte once before applying opacity; otherwise
        // their separate alpha blends would darken the outgoing image twice.
        layer.enabled: true
        opacity: 0
        z: root.activePhotoLayer === layer ? 0 : 1

        function clear() {
            opacity = 0
            imageSource = ""
            cropInfo = ({})
        }

        onReadyChanged: root.tryPhotoTransition()

        Image {
            id: photo
            objectName: root.activePhotoLayer === layer ? "photo" : "incomingPhoto"
            x: -root.smartCropRect(layer.cropInfo).x
            y: -root.smartCropRect(layer.cropInfo).y
            width: root.smartSourceWidth(layer.cropInfo)
            height: root.smartSourceHeight(layer.cropInfo)
            source: layer.imageSource
            fillMode: root.showWholeImage(layer.cropInfo) ? Image.PreserveAspectFit : Image.PreserveAspectCrop
            // Apply EXIF to the whole image, then crop by positioning it inside
            // the viewport. Decoder-level sourceClipRect runs before rotation.
            autoTransform: true
            asynchronous: true
            cache: false
            retainWhileLoading: false
            sourceSize.width: Math.ceil(width)
            sourceSize.height: Math.ceil(height)
        }
    }

    Item {
        anchors.fill: parent
        z: -1

        PhotoLayer { id: photoLayerA }
        PhotoLayer { id: photoLayerB }
    }

    Component.onCompleted: {
        root.photoLayersReady = true
        root.startPhotoTransition()
    }

    Connections {
        target: root.backend

        function onCurrentImageChanged() {
            root.startPhotoTransition()
        }

        function onCurrentCropInfoChanged() {
            if (root.backend.currentImage === root.displayedImage) {
                root.activePhotoLayer.cropInfo = root.backend.currentCropInfo
            } else if (root.backend.currentImage === root.incomingPhotoLayer.imageSource) {
                root.incomingPhotoLayer.cropInfo = root.backend.currentCropInfo
            }
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
        id: crossFade
        target: root.incomingPhotoLayer
        property: "opacity"
        from: 0.0
        to: 1.0
        duration: 900
        easing.type: Easing.InOutQuad
        // Keep the outgoing layer opaque. Fading both layers independently
        // would let the black window show through and darken the midpoint.
        onFinished: root.finishPhotoTransition()
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
                    text: root.backend.weather.temperatureText
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
                    text: root.backend.weather.conditionText
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
