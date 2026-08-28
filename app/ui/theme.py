from __future__ import annotations

from PySide6.QtGui import QFont, QPalette, QColor
from PySide6.QtWidgets import QApplication


def apply_theme(app: QApplication) -> None:
    app.setFont(QFont("Segoe UI Variable", 10))
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#0f1216"))
    palette.setColor(QPalette.WindowText, QColor("#f0f2f4"))
    palette.setColor(QPalette.Base, QColor("#12161b"))
    palette.setColor(QPalette.AlternateBase, QColor("#171c22"))
    palette.setColor(QPalette.ToolTipBase, QColor("#24292f"))
    palette.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.Text, QColor("#f0f2f4"))
    palette.setColor(QPalette.Button, QColor("#1d2126"))
    palette.setColor(QPalette.ButtonText, QColor("#f0f2f4"))
    palette.setColor(QPalette.Highlight, QColor("#4fa3ff"))
    palette.setColor(QPalette.HighlightedText, QColor("#06111f"))
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QWidget {
            font-family: "Segoe UI Variable", "Segoe UI", Arial, sans-serif;
            font-size: 10pt;
            color: #f0f2f4;
        }
        QMainWindow, QDialog {
            background: #0f1216;
        }
        QWidget#ApplicationShell {
            background: #0f1216;
        }
        QWidget#Sidebar {
            background: #0a0d11;
            border-right: 1px solid #242b33;
        }
        QWidget#SidebarBrand {
            border-bottom: 1px solid #20262d;
        }
        QLabel#SidebarTitle {
            color: #f8fafc;
            font-size: 14pt;
            font-weight: 750;
        }
        QLabel#SidebarSubtitle {
            color: #5aa7ff;
            font-size: 7.5pt;
            font-weight: 750;
        }
        QLabel#NavSectionLabel {
            color: #67727e;
            font-size: 7.5pt;
            font-weight: 750;
            padding: 6px 8px 3px 8px;
        }
        QPushButton#NavigationButton {
            background: transparent;
            border: 0;
            border-radius: 5px;
            color: #9ba6b2;
            text-align: left;
            padding: 9px 11px;
            min-height: 25px;
            font-weight: 600;
        }
        QPushButton#NavigationButton:hover {
            background: #151b22;
            border: 0;
            color: #eef4fb;
        }
        QPushButton#NavigationButton:checked {
            background: #19232e;
            border-left: 3px solid #5aa7ff;
            color: #ffffff;
            padding-left: 8px;
        }
        QLabel#SidebarStatus {
            background: #121820;
            border: 1px solid #252f39;
            border-radius: 6px;
            color: #aacdf5;
            padding: 9px 10px;
            font-size: 8.5pt;
        }
        QStackedWidget#WorkspaceStack {
            background: #0f1216;
        }
        QLabel#PageTitle {
            color: #f7f9fc;
            font-size: 17pt;
            font-weight: 750;
        }
        QLabel#PageSubtitle {
            color: #8d99a6;
            font-size: 9pt;
        }
        QLabel#PanelTitle {
            color: #f7f8f9;
            font-size: 12pt;
            font-weight: 700;
        }
        QLabel#HeroTitle {
            color: #f4f8fc;
            font-size: 15pt;
            font-weight: 750;
        }
        QLabel#StatValue {
            color: #f4f8fc;
            font-size: 12pt;
            font-weight: 750;
        }
        QLabel#StatLabel {
            color: #98a2ad;
            font-size: 7.5pt;
            font-weight: 600;
            text-transform: uppercase;
        }
        QLabel#LyricPreview {
            color: #f5f8fc;
            font-size: 19pt;
            font-weight: 750;
        }
        QLabel#TranslationPreview {
            color: #8fb5dc;
            font-size: 12pt;
            font-weight: 500;
        }
        QWidget#PreviewPanel {
            background: #171b20;
            border: 1px solid #2d343c;
            border-radius: 8px;
        }
        QLabel#Muted {
            color: #98a2ad;
        }
        QWidget#Panel {
            background: #14191f;
            border: 1px solid #29313a;
            border-radius: 7px;
        }
        QWidget#WorkSurface {
            background: #12171d;
            border: 1px solid #29313a;
            border-radius: 7px;
        }
        QWidget#InspectorSurface {
            background: #11161c;
            border: 1px solid #29313a;
            border-radius: 7px;
        }
        QWidget#CommandBar {
            background: #14191f;
            border: 1px solid #29313a;
            border-radius: 7px;
        }
        QWidget#OnlinePanel {
            background: #181c20;
            border: 1px solid #30373e;
            border-radius: 8px;
        }
        QWidget#StatChip {
            background: #141a21;
            border: 1px solid #2b3540;
            border-radius: 6px;
        }
        QLabel#PathLabel {
            background: #14171a;
            border: 1px solid #2a3036;
            border-radius: 7px;
            color: #b9c7d6;
            padding: 7px 10px;
        }
        QGroupBox {
            border: 1px solid #2a3036;
            border-radius: 6px;
            margin-top: 12px;
            padding: 12px 10px 10px 10px;
            background: #151a20;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
            color: #c8d4e2;
            font-weight: 600;
        }
        QMenuBar {
            background: #0f141b;
            color: #c8d4e2;
            border-bottom: 1px solid #253140;
        }
        QMenuBar::item:selected, QMenu::item:selected {
            background: #243447;
        }
        QMenu {
            background: #121922;
            border: 1px solid #253140;
            color: #e7edf5;
        }
        QMenu::item {
            padding: 7px 20px 7px 12px;
            min-width: 118px;
        }
        QMenu::separator {
            height: 1px;
            background: #253140;
            margin: 6px 10px;
        }
        QPushButton {
            border: 1px solid #343b43;
            border-radius: 6px;
            padding: 8px 13px;
            background: #20252a;
            color: #f0f2f4;
            font-weight: 600;
            min-height: 20px;
        }
        QPushButton:hover {
            background: #282e35;
            border-color: #4fa3ff;
        }
        QPushButton:pressed {
            background: #182739;
        }
        QPushButton:disabled {
            color: #667689;
            background: #121922;
            border-color: #253140;
        }
        QPushButton[iconOnly="true"] {
            padding: 0;
            min-width: 38px;
            max-width: 38px;
            min-height: 36px;
            max-height: 36px;
            border-radius: 9px;
        }
        QLineEdit#CompactSearch {
            min-height: 28px;
            padding: 2px 9px;
            background: #0f141a;
            border-color: #2c3742;
        }
        QPushButton#PrimaryButton {
            background: #2f88ff;
            border-color: #5ca4ff;
            color: #071019;
        }
        QPushButton#PrimaryButton:hover {
            background: #5aa4ff;
        }
        QPushButton#DangerButton {
            background: #352129;
            border-color: #86475c;
            color: #ffb8c7;
        }
        QToolButton#TransportButton {
            background: #1a2430;
            border: 1px solid #344356;
            border-radius: 17px;
            padding: 6px;
        }
        QToolButton#TransportButton:hover {
            background: #233246;
            border-color: #4fa3ff;
        }
        QToolButton#TransportButton:pressed {
            background: #182739;
        }
        QTabWidget::pane {
            border-top: 1px solid #2a3036;
            border-left: 0;
            border-right: 0;
            border-bottom: 0;
            background: #111315;
        }
        QTabBar::tab {
            padding: 12px 20px;
            border: 0;
            background: #111315;
            color: #98a2ad;
            margin: 0 2px 0 0;
            min-width: 82px;
        }
        QTabBar::tab:selected {
            background: #1c2025;
            color: #f4f8fc;
            border-bottom: 2px solid #4fa3ff;
        }
        QTabBar::tab:hover {
            background: #20252a;
            color: #dbe6f2;
        }
        QTableWidget, QListWidget, QTextEdit, QPlainTextEdit, QLineEdit, QComboBox {
            border: 1px solid #2a3036;
            border-radius: 6px;
            background: #15181c;
            color: #f0f2f4;
            selection-background-color: #244d78;
            selection-color: #ffffff;
            outline: 0;
        }
        QLineEdit#UrlInput {
            background: #0f1721;
            border-color: #30445c;
            padding: 0 10px;
            font-size: 10.5pt;
        }
        QTableWidget {
            gridline-color: #2a3036;
            alternate-background-color: #191d21;
        }
        QTableWidget::item, QListWidget::item {
            padding: 6px;
        }
        QTableWidget::item:selected, QListWidget::item:selected {
            background: #244d78;
        }
        QComboBox::drop-down {
            border: 0;
            width: 28px;
        }
        QComboBox QAbstractItemView {
            background: #111821;
            border: 1px solid #253140;
            selection-background-color: #244d78;
        }
        QHeaderView::section {
            background: #1c2025;
            color: #c6cdd5;
            border: none;
            border-right: 1px solid #2a3036;
            border-bottom: 1px solid #2a3036;
            padding: 8px;
            font-weight: 600;
        }
        QScrollBar:vertical {
            background: #101721;
            width: 10px;
        }
        QScrollBar::handle:vertical {
            background: #344356;
            border-radius: 5px;
            min-height: 24px;
        }
        QScrollBar:horizontal {
            background: #101721;
            height: 12px;
        }
        QScrollBar::handle:horizontal {
            background: #344356;
            border-radius: 5px;
            min-width: 24px;
        }
        QSplitter::handle {
            background: #2a3036;
        }
        QCheckBox {
            spacing: 8px;
        }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 1px solid #46586d;
            border-radius: 3px;
            background: #111821;
        }
        QCheckBox::indicator:checked {
            background: #4fa3ff;
            border-color: #4fa3ff;
        }
        QSlider::groove:horizontal {
            height: 6px;
            background: #253140;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #4fa3ff;
            width: 14px;
            margin: -5px 0;
            border-radius: 7px;
        }
        QProgressBar {
            border: 1px solid #344356;
            border-radius: 4px;
            text-align: center;
            background: #0f141b;
            color: #e7edf5;
            min-height: 18px;
        }
        QProgressBar::chunk {
            background: #4fa3ff;
            border-radius: 3px;
        }
        QStatusBar {
            background: #111315;
            color: #98a2ad;
            border-top: 1px solid #2a3036;
        }
        QLabel#ModeBadge {
            background: #172b3c;
            border: 1px solid #315b7d;
            border-radius: 6px;
            color: #8bc8ff;
            font-size: 8pt;
            font-weight: 700;
            padding: 5px 9px;
        }
        QLabel#SectionLabel {
            color: #89949f;
            font-size: 8pt;
            font-weight: 700;
        }
        QLabel#QualityScore {
            color: #72d6a0;
            font-size: 12pt;
            font-weight: 750;
        }
        QWidget#LyricWaveform {
            background: #0b1118;
            border: 1px solid #2a3036;
            border-radius: 8px;
        }
        QWidget#SongMap {
            background: #0d1319;
            border: 1px solid #29343e;
            border-radius: 6px;
        }
        QToolButton#CompactToolButton {
            background: #20252a;
            border: 1px solid #343b43;
            border-radius: 5px;
            min-width: 28px;
            min-height: 24px;
            padding: 2px 7px;
            font-weight: 700;
        }
        QToolButton#CompactToolButton:hover {
            background: #293039;
            border-color: #4fa3ff;
        }
        QToolButton#DisclosureButton {
            background: transparent;
            border: 0;
            color: #aeb8c2;
            padding: 7px 2px;
            font-weight: 650;
        }
        QToolButton#DisclosureButton:hover {
            color: #ffffff;
        }
        QTabWidget#InspectorTabs::pane {
            background: #16191d;
            border: 1px solid #2a3036;
            border-radius: 0 0 8px 8px;
        }
        QTabWidget#InspectorTabs QTabBar::tab {
            min-width: 44px;
            padding: 9px 3px;
            background: #15181c;
            font-size: 8.5pt;
        }
        QTabWidget#InspectorTabs QTabBar::tab:selected {
            background: #20252a;
            border-bottom: 2px solid #4fa3ff;
        }
        QListWidget#QualityList::item {
            border-bottom: 1px solid #292f35;
            padding: 9px 7px;
        }
        QListWidget#QualityList::item:selected {
            background: #263e55;
        }
        QListWidget#SectionList::item {
            border-bottom: 1px solid #283039;
            padding: 8px 6px;
        }
        QListWidget#SectionList::item:selected {
            background: #20445f;
        }
        """
    )
