import QtQuick

Item {
    id: root
    objectName: "slideshow"
    required property var backend
    signal photoRequested()
    property var activePhotoLayer: photoLayerA
    readonly property var incomingPhotoLayer: activePhotoLayer === photoLayerA ? photoLayerB : photoLayerA
    readonly property string displayedImage: activePhotoLayer.imageSource
    readonly property var displayedCropInfo: activePhotoLayer.cropInfo
    readonly property bool photoTransitionRunning: crossFade.running
    property bool photoLayersReady: false

    function startPhotoTransition() {
        if (!root.photoLayersReady) {
            return
        }

        root.photoRequested()

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

    function photoGeometry(bounds) {
        var width = Math.max(1, root.width)
        var height = Math.max(1, root.height)
        var result = {x: 0, y: 0, width: width, height: height, fit: false}
        if (!bounds || bounds.left === undefined || !bounds.image_width || !bounds.image_height) {
            return result
        }
        var imageRatio = bounds.image_width / bounds.image_height
        var viewportRatio = width / height
        var cropWidth = Math.min(1.0, viewportRatio / imageRatio)
        var cropHeight = Math.min(1.0, imageRatio / viewportRatio)
        result.fit = !!bounds.fit_only
                || (bounds.right - bounds.left) > cropWidth + 0.000001
                || (bounds.bottom - bounds.top) > cropHeight + 0.000001
        if (!result.fit) {
            result.width = imageRatio > viewportRatio ? height * imageRatio : width
            result.height = imageRatio > viewportRatio ? height : width / imageRatio
            result.x = root.cropAxis(bounds.left, bounds.right, cropWidth) * result.width
            result.y = root.cropAxis(bounds.top, bounds.bottom, cropHeight) * result.height
        }
        return result
    }

    component PhotoLayer: Rectangle {
        id: layer
        property string imageSource: ""
        property var cropInfo: ({})
        readonly property var geometry: root.photoGeometry(cropInfo)
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
            x: -layer.geometry.x
            y: -layer.geometry.y
            width: layer.geometry.width
            height: layer.geometry.height
            source: layer.imageSource
            fillMode: layer.geometry.fit ? Image.PreserveAspectFit : Image.PreserveAspectCrop
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

}
