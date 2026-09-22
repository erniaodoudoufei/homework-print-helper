from pathlib import Path

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Microsoft YaHei', sans-serif; font-size: 13px; color: #243447; }
QMainWindow, QDialog { background: #f3f6f8; }
QWidget#header, QWidget#sidebar, QWidget#adjustments { background: white; }
QLabel#appTitle { font-size: 23px; font-weight: 700; color: #183342; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; color: #183342; padding: 5px 0; }
QLabel#hint { color: #697b89; font-size: 12px; }
QLabel#eyebrow { color: #087f72; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
QLabel#emptyTitle { font-size: 25px; font-weight: 600; color: #28485a; }
QLabel#emptyText { color: #6b7f8d; font-size: 14px; line-height: 1.8; }
QLabel#notice { background: #e9f4f1; color: #286556; padding: 10px; border-radius: 7px; }
QPushButton, QToolButton { background: white; border: 1px solid #d8e1e7; border-radius: 6px; padding: 8px 11px; }
QPushButton:hover, QToolButton:hover { border-color: #83b9af; background: #f2faf7; }
QPushButton:pressed, QToolButton:checked { background: #e1f2ed; border-color: #0d8c7b; color: #086555; }
QPushButton:disabled, QToolButton:disabled { color: #a9b5bf; background: #f5f7f8; border-color: #e5eaee; }
QPushButton#primary { background: #087f72; color: white; border: 1px solid #087f72; font-weight: 600; }
QPushButton#primary:hover { background: #096b61; }
QPushButton#primary:disabled { background: #b2cec9; border-color: #b2cec9; color: #f7faf9; }
QListWidget { background: white; border: 0; outline: 0; }
QListWidget::item { border: 1px solid transparent; border-radius: 7px; padding: 10px 6px; margin: 3px 5px; }
QListWidget::item:selected { background: #e9f4f1; border-color: #85bdb1; color: #075f52; }
QListWidget::item:hover { background: #f2f6f8; }
QComboBox, QSpinBox, QDoubleSpinBox { border: 1px solid #d8e1e7; border-radius: 5px; background: white; padding: 6px 7px; min-height: 20px; }
QComboBox::drop-down { border: 0; width: 20px; }
QComboBox::down-arrow { image: url("ASSET_DIR/down.svg"); width: 12px; height: 8px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: 0; margin: 2px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: 0; margin: 2px; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("ASSET_DIR/up.svg"); width: 10px; height: 7px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("ASSET_DIR/down.svg"); width: 10px; height: 7px; }
QSlider::groove:horizontal { background: #e2e9ed; height: 5px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #36a18f; border-radius: 2px; }
QSlider::handle:horizontal { background: #087f72; width: 15px; height: 15px; margin: -5px 0; border-radius: 7px; }
QProgressBar { border: 0; border-radius: 3px; background: #e5ecef; max-height: 7px; }
QProgressBar::chunk { background: #0c9783; border-radius: 3px; }
QStatusBar { color: #6b7d89; background: #edf2f5; }
QSplitter::handle { background: #dce5eb; width: 2px; }
QToolTip { border: 1px solid #c6d9d4; background: #f7fcfa; padding: 5px; }
"""
STYLE = STYLE.replace("ASSET_DIR", (Path(__file__).resolve().parent / "assets").as_posix())
