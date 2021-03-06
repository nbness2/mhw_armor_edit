# coding: utf-8
import csv
import logging
import os
import sys
from contextlib import contextmanager
from functools import partial

from PyQt5.QtCore import Qt, QSize, QSettings, QPoint, QModelIndex
from PyQt5.QtGui import QKeySequence, QIcon
from PyQt5.QtWidgets import (QApplication, QMainWindow, QFileSystemModel,
                             QTreeView, QStyle,
                             QFileDialog, QTabWidget, QBoxLayout,
                             QWidget, QMessageBox, QDockWidget, QLabel,
                             QVBoxLayout, QLineEdit, QStatusBar, QDialog)

from mhw_armor_edit.assets import Assets
from mhw_armor_edit.editor.models import FilePluginRegistry
from mhw_armor_edit.models import Workspace, Directory
from mhw_armor_edit.utils import create_action


STATUSBAR_MESSAGE_TIMEOUT = 10 * 1000
ABOUT_TEXT = """<h3>MHW Editor Suite</h3>
<table cellspacing="10">
<tr><td>Version:</td><td>v1.6.0-alpha</td></tr>
<tr><td>Release-Date:</td><td>2018-12-23</td></tr>
<tr><td>URL:</td><td><a href="https://github.com/fre-sch/mhw_armor_edit/releases">
    https://github.com/fre-sch/mhw_armor_edit/releases</a></td>
</tr>
</table>
"""
log = logging.getLogger()
LANG = (
    ("jpn", "Japanese"),
    ("eng", "English"),
    ("fre", "French"),
    ("spa", "Spanish"),
    ("ger", "German"),
    ("ita", "Italian"),
    ("kor", "Korean"),
    ("chT", "Chinese"),
    ("rus", "Russian"),
    ("pol", "Polish"),
    ("ptB", "Portuguese"),
    ("ara", "Arabic"),
)


@contextmanager
def show_error_dialog(parent, title="Error"):
    try:
        yield
    except Exception as e:
        QMessageBox.warning(parent, title, str(e), QMessageBox.Ok, QMessageBox.Ok)


class EditorView(QWidget):
    def __init__(self, workspace_file, child_widget, parent=None):
        super().__init__(parent)
        self.workspace_file = workspace_file
        layout = QBoxLayout(QBoxLayout.TopToBottom)
        self.setLayout(layout)
        child_widget.set_model(self.workspace_file)
        layout.addWidget(child_widget)
        self.workspace_file.reloaded.connect(
            lambda: child_widget.set_model(self.workspace_file)
        )
        self.workspace_file.modifiedChanged.connect(
            self.handle_workspace_file_modified_changed
        )

    def handle_workspace_file_modified_changed(self, modified):
        tab_widget = self.parent().parent()
        tab_index = tab_widget.indexOf(self)
        title = f"{self.workspace_file.directory.name}: {self.workspace_file.rel_path}"
        if modified:
            title += "*"
        tab_widget.setTabText(tab_index, title)

    @classmethod
    def factory(cls, parent, workspace_file):
        plugin = FilePluginRegistry.get_plugin(workspace_file.abs_path)
        widget_inst = plugin.widget_factory()
        inst = cls(workspace_file, widget_inst, parent)
        return inst


class DirectoryDockWidget(QWidget):
    def __init__(self, directory: Directory, filtered=False, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.setLayout(layout)
        self.path_label = QLineEdit()
        self.path_label.setReadOnly(True)
        layout.addWidget(self.path_label)
        self.tree_view = QTreeView()
        layout.addWidget(self.tree_view)
        self.directory = directory
        self.filtered = filtered
        self.tree_view.setModel(QFileSystemModel())
        for i in range(1, 4):
            self.tree_view.hideColumn(i)
        self.tree_view.setHeaderHidden(True)
        self.directory.changed.connect(self.handle_directory_path_changed)

    def handle_directory_path_changed(self, path):
        if not path:
            return
        self.path_label.setText(path)
        model = self.tree_view.model()
        model.setRootPath(path)
        self.tree_view.setRootIndex(model.index(path))
        if self.filtered:
            model.setNameFilters(
                plugin.pattern for plugin in FilePluginRegistry.plugins
            )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.chunk_directory = Directory(
            "CHUNK",
            QIcon(Assets.get_asset_path("document_a4_locked.png")),
            None)
        self.mod_directory = Directory(
            "MOD",
            QIcon(Assets.get_asset_path("document_a4.png")),
            None)
        self.workspace = Workspace([self.mod_directory, self.chunk_directory],
                                   parent=self)
        self.workspace.fileOpened.connect(self.handle_workspace_file_opened)
        self.workspace.fileClosed.connect(self.handle_workspace_file_closed)
        self.workspace.fileActivated.connect(self.handle_workspace_file_activated)
        self.workspace.fileLoadError.connect(self.handle_workspace_file_load_error)
        self.init_actions()
        self.init_menu_bar()
        self.init_toolbar()
        self.setStatusBar(QStatusBar())
        self.setWindowTitle("MHW-Editor-Suite")
        self.init_file_tree(
            self.chunk_directory, "Chunk directory",
            self.open_chunk_directory_action,
            filtered=True)
        self.init_file_tree(
            self.mod_directory,
            "Mod directory",
            self.open_mod_directory_action)
        self.setCentralWidget(self.init_editor_tabs())
        self.load_settings()

    def closeEvent(self, event):
        self.write_settings()

    def load_settings(self):
        self.settings = QSettings(QSettings.IniFormat, QSettings.UserScope,
                                  "fre-sch.github.com",
                                  "MHW-Editor-Suite")
        self.settings.beginGroup("MainWindow")
        size = self.settings.value("size", QSize(1000, 800))
        position = self.settings.value("position", QPoint(300, 300))
        self.settings.endGroup()
        self.settings.beginGroup("Application")
        chunk_directory = self.settings.value("chunk_directory", None)
        mod_directory = self.settings.value("mod_directory", None)
        lang = self.settings.value("lang", None)
        self.settings.endGroup()
        self.resize(size)
        self.move(position)
        if chunk_directory:
            self.chunk_directory.set_path(chunk_directory)
        if mod_directory:
            self.mod_directory.set_path(mod_directory)
        if lang:
            self.handle_set_lang_action(lang)

    def write_settings(self):
        self.settings.beginGroup("MainWindow")
        self.settings.setValue("size", self.size())
        self.settings.setValue("position", self.pos())
        self.settings.endGroup()
        self.settings.beginGroup("Application")
        self.settings.setValue("chunk_directory", self.chunk_directory.path)
        self.settings.setValue("mod_directory", self.mod_directory.path)
        self.settings.setValue("lang", FilePluginRegistry.lang)
        self.settings.endGroup()

    def get_icon(self, name):
        return self.style().standardIcon(name)

    def init_actions(self):
        self.open_chunk_directory_action = create_action(
            self.get_icon(QStyle.SP_DirOpenIcon),
            "Open chunk_directory ...",
            self.handle_open_chunk_directory,
            None)
        self.open_mod_directory_action = create_action(
            self.get_icon(QStyle.SP_DirOpenIcon),
            "Open mod directory ...",
            self.handle_open_mod_directory,
            QKeySequence.Open)
        self.save_file_action = create_action(
            self.get_icon(QStyle.SP_DriveHDIcon),
            "Save file",
            self.handle_save_file_action,
            QKeySequence.Save)
        self.save_file_action.setDisabled(True)
        self.export_csv_action = create_action(
            self.get_icon(QStyle.SP_FileIcon),
            "Export file to CSV...",
            self.handle_export_file_action)
        self.export_csv_action.setDisabled(True)
        self.about_action = create_action(
            None, "About", self.handle_about_action)
        self.lang_actions = {
            lang: create_action(
                None, name, partial(self.handle_set_lang_action, lang),
                checkable=True)
            for lang, name in LANG
        }

    def init_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        file_menu.insertAction(None, self.open_chunk_directory_action)
        file_menu.insertAction(None, self.open_mod_directory_action)
        file_menu.insertAction(None, self.export_csv_action)
        file_menu.insertAction(None, self.save_file_action)
        lang_menu = menubar.addMenu("Language")
        for action in self.lang_actions.values():
            lang_menu.insertAction(None, action)
        help_menu = menubar.addMenu("Help")
        help_menu.insertAction(None, self.about_action)

    def init_toolbar(self):
        toolbar = self.addToolBar("Main")
        toolbar.setIconSize(QSize(16, 16))
        toolbar.setFloatable(False)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.insertAction(None, self.open_mod_directory_action)
        toolbar.insertAction(None, self.save_file_action)

    def init_file_tree(self, directory, title, action, filtered=False):
        widget = DirectoryDockWidget(directory, filtered=filtered, parent=self)
        widget.path_label.addAction(action, QLineEdit.LeadingPosition)
        widget.tree_view.activated.connect(
            partial(self.handle_directory_tree_view_activated, directory))
        dock = QDockWidget(title, self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetMovable)
        dock.setWidget(widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def handle_directory_tree_view_activated(self, directory, qindex: QModelIndex):
        if qindex.model().isDir(qindex):
            return
        file_path = qindex.model().filePath(qindex)
        self.workspace.open_file(directory, file_path)

    def init_editor_tabs(self):
        self.editor_tabs = QTabWidget()
        self.editor_tabs.setDocumentMode(True)
        self.editor_tabs.setTabsClosable(True)
        self.editor_tabs.tabCloseRequested.connect(
            self.handle_editor_tab_close_requested)
        return self.editor_tabs

    def handle_workspace_file_opened(self, path, rel_path):
        ws_file = self.workspace.files[path]
        editor_view = EditorView.factory(self.editor_tabs, ws_file)
        editor_view.setObjectName(path)
        self.editor_tabs.addTab(editor_view,
                                ws_file.directory.file_icon,
                                f"{ws_file.directory.name}: {rel_path}")
        self.editor_tabs.setCurrentWidget(editor_view)
        self.save_file_action.setDisabled(False)
        self.export_csv_action.setDisabled(False)

    def handle_workspace_file_activated(self, path, rel_path):
        widget = self.editor_tabs.findChild(QWidget, path)
        self.editor_tabs.setCurrentWidget(widget)

    def handle_workspace_file_closed(self, path, rel_path):
        widget = self.editor_tabs.findChild(QWidget, path)
        widget.deleteLater()
        self.save_file_action.setDisabled(not self.workspace.files)
        self.export_csv_action.setDisabled(not self.workspace.files)

    def handle_workspace_file_load_error(self, path, rel_path, error):
        QMessageBox.warning(self, f"Error loading file `{rel_path}`",
                            f"Error while loading\n{path}:\n\n{error}",
                            QMessageBox.Ok, QMessageBox.Ok)

    def handle_editor_tab_close_requested(self, tab_index):
        editor_view = self.editor_tabs.widget(tab_index)
        self.workspace.close_file(editor_view.workspace_file)

    def handle_open_chunk_directory(self):
        path = QFileDialog.getExistingDirectory(parent=self,
                                                caption="Open chunk directory")
        if path:
            self.chunk_directory.set_path(os.path.normpath(path))

    def handle_open_mod_directory(self):
        path = QFileDialog.getExistingDirectory(parent=self,
                                                caption="Open mod directory")
        if path:
            self.mod_directory.set_path(os.path.normpath(path))

    def handle_save_file_action(self):
        editor = self.editor_tabs.currentWidget()
        main_ws_file = editor.workspace_file
        for ws_file in main_ws_file.get_files_modified():
            if ws_file.directory is self.chunk_directory:
                if self.mod_directory.is_valid:
                    self.transfer_file_to_mod_workspace(
                        ws_file, ws_file is main_ws_file)
                else:
                    self.save_base_content_file(ws_file)
            else:
                with show_error_dialog(self, "Error writing file"):
                    self.save_workspace_file(ws_file)

    def handle_export_file_action(self):
        editor = self.editor_tabs.currentWidget()
        ws_file = editor.workspace_file
        file_name, file_type = QFileDialog.getSaveFileName(self, "Export file as CSV")
        if file_name:
            if not file_name.endswith(".csv"):
                file_name += ".csv"
            with show_error_dialog(self, "Error exporting file"):
                self.write_csv(ws_file, file_name)
                self.statusBar().showMessage(
                    f"Export '{file_name}' finished.", STATUSBAR_MESSAGE_TIMEOUT)

    def handle_set_lang_action(self, lang):
        FilePluginRegistry.lang = lang
        for act in self.lang_actions.values():
            act.setChecked(False)
        self.lang_actions[lang].setChecked(True)

    def write_csv(self, ws_file, file_name):
        with open(file_name, "w") as fp:
            csv_writer = csv.writer(
                fp, delimiter=",", doublequote=False, escapechar='\\',
                lineterminator="\n")
            cls = type(ws_file.data)
            fields = cls.EntryFactory.fields()
            csv_writer.writerow(fields)
            for entry in ws_file.data.entries:
                csv_writer.writerow(entry.values())

    def save_base_content_file(self, ws_file):
        result = QMessageBox.question(
            self, "Save base content file?",
            "Do you really want to update this chunk file?",
            QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
        if result == QMessageBox.Ok:
            with show_error_dialog(self, "Error writing file"):
                self.save_workspace_file(ws_file)

    def transfer_file_to_mod_workspace(self, ws_file, reopen=False):
        mod_abs_path, exists = self.mod_directory.get_child_path(ws_file.rel_path)
        if not exists:
            return self.transfer_file(ws_file, self.mod_directory, reopen)

        result = QMessageBox.question(
            self,
            "File exists, overwrite?",
            f"File '{ws_file.rel_path}' already found in mod directory, overwrite?",
            QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Ok)
        if result == QMessageBox.Ok:
            self.transfer_file(ws_file, self.mod_directory, reopen)

    def transfer_file(self, ws_file, target_directory, reopen=False):
        if target_directory is ws_file.directory:
            return
        self.workspace.close_file(ws_file)
        ws_file.set_directory(target_directory)
        self.save_workspace_file(ws_file)
        if reopen:
            self.workspace.open_file(target_directory, ws_file.abs_path)

    def save_workspace_file(self, ws_file):
        ws_file.save()
        self.statusBar().showMessage(
            f"File '{ws_file.abs_path}' saved.", STATUSBAR_MESSAGE_TIMEOUT)

    def handle_about_action(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About MHW Editor Suite")
        layout = QVBoxLayout()
        dialog.setLayout(layout)
        about_text = QLabel(ABOUT_TEXT)
        about_text.setTextFormat(Qt.RichText)
        about_text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        about_text.setOpenExternalLinks(True)
        layout.addWidget(about_text)
        dialog.exec()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format="%(levelname)s %(message)s")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(Assets.get_asset_path("icon32.svg")))
    app.setStyleSheet("""
    QMainWindow::separator:vertical,
    QSplitter::handle:horizontal {
        width: 0px;
        margin: 0 6px;
        max-height: 100px;
        border-left: 1px dotted palette(dark);
        border-right: 1px dotted palette(base);
    }
    QMainWindow::separator:horizontal,
    QSplitter::handle:vertical {
        height: 0px;
        margin: 6px 0;
        border-top: 1px dotted palette(dark);
        border-bottom: 1px dotted palette(base);
    }
    QDockWidget::title {
        padding-top: 1ex;
        background-color: palette(window);
    }
    """)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
