# Third-party components

This application bundles unmodified publicly available Python wheels and their runtime dependencies. Original notices are copied to `licenses`. Component source and build versions are listed below; the application source and reproducible build script are supplied alongside the delivery.

| Component | Version | Source / notices |
|---|---|---|
| Python | 3.12.3 | https://www.python.org/downloads/release/python-3123/ ; PSF license |
| PySide6 / Shiboken6 / Qt | 6.11.2 | https://code.qt.io/cgit/pyside/pyside-setup.git/ ; LGPL-3.0 open-source option, component-specific notices apply |
| OpenCV Python headless | 4.14.0.94 | https://github.com/opencv/opencv-python ; bundled LICENSE and LICENSE-3RD-PARTY |
| NumPy | 2.5.3 | https://github.com/numpy/numpy ; bundled license notices |
| Pillow | 12.3.0 | https://github.com/python-pillow/Pillow ; bundled license notices |
| PyInstaller bootloader | 6.22.3 | https://github.com/pyinstaller/pyinstaller ; GPL with bootloader exception |

Qt is dynamically linked in the `_internal` directory. The application does not restrict replacing compatible Qt / PySide library files, or reverse engineering for debugging modifications of those libraries. The sources for Qt modules are available from https://download.qt.io/official_releases/qt/ and https://code.qt.io/ . Qt for Python's licensing overview is https://doc.qt.io/qtforpython-6/licenses.html .

Windows system fonts are referenced at runtime and are not included in this distribution. Microsoft runtime notices, when bundled by PyInstaller, remain with the runtime files.
