from PyQt6.QtCore import QMargins,QRect,Qt
from PyQt6.QtWidgets import QLabel,QPushButton

STYLE = '''
QMainWindow, QWidget#AppRoot, QWidget#ContentShell {background:#F4F3F6;color:#292633;}
QDialog {background:#F4F3F6;color:#292633;}
QWidget {font-family:"Segoe UI";font-size:10pt;color:#292633;}
QFrame#NavigationRail {background:#292333;border:0;}
QLabel#Brand {color:white;font-size:20pt;font-weight:700;background:transparent;}
QLabel#BrandMark {background:transparent;}
QLabel#RailSubtitle {color:#CDC4D8;font-size:9pt;background:transparent;}
QLabel#PilotState {color:#EAE3F2;background:#3B3149;border:1px solid #554662;border-radius:5px;padding:9px;font-size:9pt;}
QPushButton#SidebarButton {background:transparent;color:#DED8E6;border:0;text-align:left;padding:13px 12px;border-radius:5px;}
QPushButton#SidebarButton:checked {background:#EDE6F5;color:#3F2B5C;font-weight:600;}
QPushButton#SidebarButton:hover {background:#453650;color:white;}
QPushButton#SidebarButton:checked:hover {background:#E3D7F0;color:#3F2B5C;}
QLabel#PageTitle {font-size:20pt;font-weight:600;}
QLabel#Subtitle {color:#6A6374;}
QLabel#RunStatus {background:#EEEBF2;border:1px solid #DDD9E4;padding:10px 12px;border-radius:6px;}
QFrame#Card {background:white;border:1px solid #DDD9E4;border-radius:7px;}
QLabel#CardTitle {font-size:12pt;font-weight:600;background:transparent;}
QPushButton {background:white;border:1px solid #D5CFDE;border-radius:5px;padding:8px 12px;min-height:22px;}
QPushButton:hover {background:#EDE6F5;border-color:#9B82BA;}
QPushButton:pressed {background:#E2D7EF;}
QPushButton#PrimaryButton {background:#7150A1;color:white;border-color:#7150A1;font-weight:600;}
QPushButton#PrimaryButton:hover {background:#60428C;border-color:#60428C;}
QPushButton:disabled {color:#8D8796;background:#ECE9F0;border-color:#DDD9E4;}
QPushButton#PrimaryButton:disabled {color:#8D8796;background:#ECE9F0;border-color:#DDD9E4;}
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTableView:focus, QListWidget:focus {border:2px solid #7150A1;}
QLineEdit,QComboBox,QPlainTextEdit {background:white;border:1px solid #D5CFDE;border-radius:4px;padding:7px;selection-background-color:#EDE6F5;selection-color:#292633;}
QComboBox QAbstractItemView {background:#FFFFFF;color:#292633;alternate-background-color:#F8F6FA;selection-background-color:#EDE6F5;selection-color:#292633;border:1px solid #D5CFDE;outline:0;}
QComboBox QAbstractItemView::item {background:#FFFFFF;color:#292633;min-height:28px;padding:4px 8px;}
QComboBox QAbstractItemView::item:selected {background:#EDE6F5;color:#292633;}
QMenu {background:#FFFFFF;color:#292633;border:1px solid #D5CFDE;}
QMenu::item:selected {background:#EDE6F5;color:#292633;}
QToolTip {background:#FFFFFF;color:#292633;border:1px solid #D5CFDE;}
QLabel#SourceBadge {background:#EEEBF2;color:#6A6374;border:1px solid #DDD9E4;border-radius:5px;padding:5px 8px;font-size:9pt;}
QLabel#SourceBadge[found="true"] {background:#EAF2EC;color:#365C41;border-color:#C9DCCC;}
QTableView,QTableWidget,QTextBrowser,QListWidget {background:white;alternate-background-color:#F8F6FA;border:1px solid #DDD9E4;border-radius:4px;selection-background-color:#EDE6F5;selection-color:#292633;}
QHeaderView::section {background:#EEEBF2;color:#51465F;border:0;border-bottom:1px solid #DDD9E4;padding:8px;text-align:left;font-weight:600;}
QTableView::item {padding:5px;border-bottom:1px solid #EEEAF2;}
QTabWidget::pane {border:1px solid #DDD9E4;background:white;}
QTabBar::tab {background:#ECE8F1;color:#655B70;padding:10px 15px;border:1px solid #DDD9E4;}
QTabBar::tab:selected {background:white;color:#65418F;font-weight:600;}
QStatusBar {background:#EEEBF2;color:#6A6374;}
QSplitter::handle {background:#DDD9E4;}
QProgressBar {background:#E7E1ED;border:0;border-radius:3px;max-height:6px;}
QProgressBar::chunk {background:#7150A1;border-radius:3px;}
'''


def label(text='', name=None):
    item=QLabel(text);item.setTextFormat(Qt.TextFormat.PlainText);item.setWordWrap(True)
    if name:item.setObjectName(name)
    return item


def button(text, callback, primary=False):
    item=QPushButton(text);item.clicked.connect(callback)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:item.setObjectName('PrimaryButton')
    return item


def initial_window_geometry(available, frame_margins=None):
    """Fit the preferred client area and its native frame on one screen."""
    margins=frame_margins if frame_margins is not None else QMargins(8,32,8,8)
    horizontal=margins.left()+margins.right();vertical=margins.top()+margins.bottom()
    if not available.isValid() or available.width()<=horizontal or available.height()<=vertical:
        raise ValueError('Skjermens tilgjengelige arbeidsområde er for lite.')
    padding=min(12,(available.width()-horizontal-1)//2,(available.height()-vertical-1)//2)
    width=min(1500,available.width()-2*padding-horizontal)
    height=min(940,available.height()-2*padding-vertical)
    x=available.x()+(available.width()-width-horizontal)//2+margins.left()
    y=available.y()+(available.height()-height-vertical)//2+margins.top()
    return QRect(x,y,width,height)


