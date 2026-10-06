import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.VectorImage

Item {
    id: root
    required property var backend
    required property bool controlsVisible
    required property bool metadataVisible
    readonly property bool shutdownHolding: shutdownHoldTimer.running
    signal controlsRequested()
    signal shutdownRequested()
    readonly property bool isPortrait: root.height >= root.width
    readonly property bool useQrcAssets: root.backend.weatherIcon.indexOf("qrc:/") === 0
    readonly property int actionButtonSize: root.isPortrait ? 60 : 50
    readonly property int actionIconSize: root.isPortrait ? 29 : 24
    readonly property int actionBusySize: root.isPortrait ? 28 : 24

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

    function revealControls() {
        root.controlsRequested()
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
                                root.shutdownRequested()
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
