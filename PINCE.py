# -*- coding: utf-8 -*-
# !/usr/bin/env python3
"""
Copyright (C) 2016 Korcan Karaokçu <korcankaraokcu@gmail.com>
Copyright (C) 2016 Çağrı Ulaş <cagriulas@gmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
from PyQt5.QtGui import QIcon, QMovie, QPixmap, QCursor, QKeySequence, QColor
from PyQt5.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QMessageBox, QDialog, QCheckBox, QWidget, \
    QShortcut, QKeySequenceEdit, QTabWidget, QMenu, QFileDialog
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QByteArray, QSettings, QCoreApplication, QEvent, \
    QItemSelectionModel, QTimer
from time import sleep, time
from threading import Thread
import os
import webbrowser
import sys
import traceback

from libPINCE import GuiUtils
from libPINCE import SysUtils
from libPINCE import GDB_Engine
from libPINCE import type_defs

from GUI.MainWindow import Ui_MainWindow as MainWindow
from GUI.SelectProcess import Ui_MainWindow as ProcessWindow
from GUI.AddAddressManuallyDialog import Ui_Dialog as ManualAddressDialog
from GUI.LoadingWidget import Ui_Form as LoadingWidget
from GUI.DialogWithButtons import Ui_Dialog as DialogWithButtons
from GUI.SettingsDialog import Ui_Dialog as SettingsDialog
from GUI.ConsoleWidget import Ui_Form as ConsoleWidget
from GUI.AboutWidget import Ui_TabWidget as AboutWidget
from GUI.MemoryViewerWindow import Ui_MainWindow as MemoryViewWindow
from GUI.BookmarkWidget import Ui_Form as BookmarkWidget
from GUI.FloatRegisterWidget import Ui_TabWidget as FloatRegisterWidget
from GUI.StackTraceInfoWidget import Ui_Form as StackTraceInfoWidget

from GUI.CustomAbstractTableModels.HexModel import QHexModel
from GUI.CustomAbstractTableModels.AsciiModel import QAsciiModel

selfpid = os.getpid()

# settings
update_table = bool
table_update_interval = float
pause_hotkey = str
continue_hotkey = str
code_injection_method = int
bring_disassemble_to_front = bool
instructions_per_scroll = int

# row colours for disassemble qtablewidget
PC_COLOUR = Qt.blue
BOOKMARK_COLOUR = Qt.yellow
DEFAULT_COLOUR = Qt.white

# represents the index of columns in address table
FROZEN_COL = 0  # Frozen
DESC_COL = 1  # Description
ADDR_COL = 2  # Address
TYPE_COL = 3  # Type
VALUE_COL = 4  # Value

# represents the index of columns in disassemble table
DISAS_ADDR_COL = 0
DISAS_BYTES_COL = 1
DISAS_OPCODES_COL = 2
DISAS_COMMENT_COL = 3

# represents the index of columns in floating point table
FLOAT_REGISTERS_NAME_COL = 0
FLOAT_REGISTERS_VALUE_COL = 1

# represents the index of columns in stacktrace table
STACKTRACE_RETURN_ADDRESS_COL = 0
STACKTRACE_FRAME_ADDRESS_COL = 1

# represents the index of columns in stack table
STACK_POINTER_ADDRESS_COL = 0
STACK_VALUE_COL = 1
STACK_INT_REPRESENTATION_COL = 2
STACK_FLOAT_REPRESENTATION_COL = 3

# represents row and column counts of Hex table
HEX_VIEW_COL_COUNT = 16
HEX_VIEW_ROW_COUNT = 42  # J-JUST A COINCIDENCE, I SWEAR!

INDEX_BYTE = type_defs.VALUE_INDEX.INDEX_BYTE
INDEX_2BYTES = type_defs.VALUE_INDEX.INDEX_2BYTES
INDEX_4BYTES = type_defs.VALUE_INDEX.INDEX_4BYTES
INDEX_8BYTES = type_defs.VALUE_INDEX.INDEX_8BYTES
INDEX_FLOAT = type_defs.VALUE_INDEX.INDEX_FLOAT
INDEX_DOUBLE = type_defs.VALUE_INDEX.INDEX_DOUBLE
INDEX_STRING = type_defs.VALUE_INDEX.INDEX_STRING
INDEX_AOB = type_defs.VALUE_INDEX.INDEX_AOB

INFERIOR_RUNNING = type_defs.INFERIOR_STATUS.INFERIOR_RUNNING
INFERIOR_STOPPED = type_defs.INFERIOR_STATUS.INFERIOR_STOPPED

SIMPLE_DLOPEN_CALL = type_defs.INJECTION_METHOD.SIMPLE_DLOPEN_CALL
ADVANCED_INJECTION = type_defs.INJECTION_METHOD.ADVANCED_INJECTION

ARCH_32 = type_defs.INFERIOR_ARCH.ARCH_32
ARCH_64 = type_defs.INFERIOR_ARCH.ARCH_64

# From version 5.5 and onwards, PyQT calls qFatal() when an exception has been encountered
# So, we must override sys.excepthook to avoid calling of qFatal()
sys.excepthook = traceback.print_exception


# Checks if the inferior has been terminated
class AwaitProcessExit(QThread):
    process_exited = pyqtSignal()

    def run(self):
        while GDB_Engine.currentpid is 0 or SysUtils.is_process_valid(GDB_Engine.currentpid):
            sleep(0.01)
        self.process_exited.emit()


# Await async output from gdb
class AwaitAsyncOutput(QThread):
    async_output_ready = pyqtSignal()

    def run(self):
        while True:
            with GDB_Engine.gdb_async_condition:
                GDB_Engine.gdb_async_condition.wait()
            self.async_output_ready.emit()


class CheckInferiorStatus(QThread):
    process_stopped = pyqtSignal()
    process_running = pyqtSignal()

    def run(self):
        while True:
            with GDB_Engine.status_changed_condition:
                GDB_Engine.status_changed_condition.wait()
            if GDB_Engine.inferior_status is INFERIOR_STOPPED:
                self.process_stopped.emit()
            else:
                self.process_running.emit()


class UpdateAddressTableThread(QThread):
    update_table_signal = pyqtSignal()

    def run(self):
        while True:
            while not update_table:
                sleep(0.1)
            if GDB_Engine.inferior_status is INFERIOR_STOPPED:
                self.update_table_signal.emit()
            sleep(table_update_interval)


# A thread that updates the address table constantly
# planned for future
class UpdateAddressTable_planned(QThread):
    def __init__(self, pid):
        super().__init__()
        self.pid = pid

    # communicates with the inferior via files and reads the values from them
    # planned for future
    def run(self):
        SysUtils.do_cleanups(self.pid)
        directory_path = SysUtils.get_PINCE_IPC_directory(self.pid)
        SysUtils.is_path_valid(directory_path, "create")
        send_file = directory_path + "/PINCE-to-Inferior.txt"
        recv_file = directory_path + "/Inferior-to-PINCE.txt"
        status_file = directory_path + "/status.txt"
        abort_file = directory_path + "/abort.txt"
        open(send_file, "w").close()
        open(recv_file, "w").close()
        FILE = open(status_file, "w")

        # Inferior will try to check PINCE's presence with this information
        FILE.write(str(selfpid))
        FILE.close()
        SysUtils.fix_path_permissions(send_file)
        SysUtils.fix_path_permissions(recv_file)
        SysUtils.fix_path_permissions(status_file)
        while True:
            sleep(0.01)
            status_word = "waiting"
            while status_word not in "sync-request-recieve":
                sleep(0.01)
                status = open(status_file, "r")
                status_word = status.read()
                status.close()
                try:
                    abort = open(abort_file, "r")
                    abort.close()
                    return
                except:
                    pass
            status = open(status_file, "w")
            status.write("sync-request-send")
            status.close()
            FILE = open(send_file, "w")
            FILE.close()
            FILE = open(recv_file, "r")
            readed = FILE.read()
            # print(readed)
            FILE.close()


# the mainwindow
class MainForm(QMainWindow, MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        GuiUtils.center(self)
        self.tableWidget_addresstable.setColumnWidth(FROZEN_COL, 25)
        self.tableWidget_addresstable.setColumnWidth(DESC_COL, 150)
        self.tableWidget_addresstable.setColumnWidth(ADDR_COL, 150)
        self.tableWidget_addresstable.setColumnWidth(TYPE_COL, 120)
        QCoreApplication.setOrganizationName("PINCE")
        QCoreApplication.setOrganizationDomain("github.com/korcankaraokcu/PINCE")
        QCoreApplication.setApplicationName("PINCE")
        self.settings = QSettings()
        if not SysUtils.is_path_valid(self.settings.fileName()):
            self.set_default_settings()
        try:
            self.apply_settings()
        except:
            self.settings.clear()
            self.set_default_settings()
        self.memory_view_window = MemoryViewWindowForm()
        self.memory_view_window.address_added.connect(self.add_entry_to_addresstable)
        self.await_exit_thread = AwaitProcessExit()
        self.await_exit_thread.process_exited.connect(self.on_inferior_exit)
        self.await_exit_thread.start()
        self.check_status_thread = CheckInferiorStatus()
        self.check_status_thread.process_stopped.connect(self.on_status_stopped)
        self.check_status_thread.process_running.connect(self.on_status_running)
        self.check_status_thread.process_stopped.connect(self.memory_view_window.process_stopped)
        self.check_status_thread.process_running.connect(self.memory_view_window.process_running)
        self.check_status_thread.start()
        self.update_address_table_thread = UpdateAddressTableThread()
        self.update_address_table_thread.update_table_signal.connect(self.update_address_table_manually)
        self.update_address_table_thread.start()
        self.shortcut_pause = QShortcut(QKeySequence(pause_hotkey), self)
        self.shortcut_pause.activated.connect(self.pause_hotkey_pressed)
        self.shortcut_continue = QShortcut(QKeySequence(continue_hotkey), self)
        self.shortcut_continue.activated.connect(self.continue_hotkey_pressed)
        self.tableWidget_addresstable.keyPressEvent = self.tableWidget_addresstable_keyPressEvent
        self.processbutton.clicked.connect(self.processbutton_onclick)
        self.pushButton_NewFirstScan.clicked.connect(self.newfirstscan_onclick)
        self.pushButton_NextScan.clicked.connect(self.nextscan_onclick)
        self.pushButton_Settings.clicked.connect(self.settingsbutton_onclick)
        self.pushButton_Console.clicked.connect(self.consolebutton_onclick)
        self.pushButton_Wiki.clicked.connect(self.wikibutton_onclick)
        self.pushButton_About.clicked.connect(self.aboutbutton_onclick)
        self.pushButton_AddAddressManually.clicked.connect(self.addaddressmanually_onclick)
        self.pushButton_MemoryView.clicked.connect(self.memoryview_onlick)
        self.pushButton_RefreshAdressTable.clicked.connect(self.update_address_table_manually)
        self.pushButton_CleanAddressTable.clicked.connect(self.delete_address_table_contents)
        self.tableWidget_addresstable.itemDoubleClicked.connect(self.on_address_table_double_click)
        icons_directory = SysUtils.get_current_script_directory() + "/media/icons"
        self.processbutton.setIcon(QIcon(QPixmap(icons_directory + "/monitor.png")))
        self.pushButton_Open.setIcon(QIcon(QPixmap(icons_directory + "/folder.png")))
        self.pushButton_Save.setIcon(QIcon(QPixmap(icons_directory + "/disk.png")))
        self.pushButton_Settings.setIcon(QIcon(QPixmap(icons_directory + "/wrench.png")))
        self.pushButton_CopyToAddressTable.setIcon(QIcon(QPixmap(icons_directory + "/arrow_down.png")))
        self.pushButton_CleanAddressTable.setIcon(QIcon(QPixmap(icons_directory + "/bin_closed.png")))
        self.pushButton_RefreshAdressTable.setIcon(QIcon(QPixmap(icons_directory + "/table_refresh.png")))
        self.pushButton_Console.setIcon(QIcon(QPixmap(icons_directory + "/application_xp_terminal.png")))
        self.pushButton_Wiki.setIcon(QIcon(QPixmap(icons_directory + "/book_open.png")))
        self.pushButton_About.setIcon(QIcon(QPixmap(icons_directory + "/information.png")))

    def set_default_settings(self):
        self.settings.beginGroup("General")
        self.settings.setValue("auto_update_address_table", True)
        self.settings.setValue("address_table_update_interval", 0.5)
        self.settings.endGroup()
        self.settings.beginGroup("Hotkeys")
        self.settings.setValue("pause", "F2")
        self.settings.setValue("continue", "F3")
        self.settings.endGroup()
        self.settings.beginGroup("CodeInjection")
        self.settings.setValue("code_injection_method", SIMPLE_DLOPEN_CALL)
        self.settings.endGroup()
        self.settings.beginGroup("Disassemble")
        self.settings.setValue("bring_disassemble_to_front", False)
        self.settings.setValue("instructions_per_scroll", 2)
        self.settings.endGroup()
        self.apply_settings()

    def apply_settings(self):
        global update_table
        global table_update_interval
        global pause_hotkey
        global continue_hotkey
        global code_injection_method
        global bring_disassemble_to_front
        global instructions_per_scroll
        update_table = self.settings.value("General/auto_update_address_table", type=bool)
        table_update_interval = self.settings.value("General/address_table_update_interval", type=float)
        pause_hotkey = self.settings.value("Hotkeys/pause")
        continue_hotkey = self.settings.value("Hotkeys/continue")
        try:
            self.shortcut_pause.setKey(QKeySequence(pause_hotkey))
        except AttributeError:
            pass
        try:
            self.shortcut_continue.setKey(QKeySequence(continue_hotkey))
        except AttributeError:
            pass
        code_injection_method = self.settings.value("CodeInjection/code_injection_method", type=int)
        bring_disassemble_to_front = self.settings.value("Disassemble/bring_disassemble_to_front", type=bool)
        instructions_per_scroll = self.settings.value("Disassemble/instructions_per_scroll", type=int)

    def pause_hotkey_pressed(self):
        GDB_Engine.interrupt_inferior()

    def continue_hotkey_pressed(self):
        GDB_Engine.continue_inferior()

    # I don't know if this is some kind of retarded hack
    def tableWidget_addresstable_keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete:
            selected_rows = self.tableWidget_addresstable.selectionModel().selectedRows()
            for item in selected_rows:
                self.tableWidget_addresstable.removeRow(item.row())

    def update_address_table_manually(self):
        table_contents = []
        row_count = self.tableWidget_addresstable.rowCount()
        for row in range(row_count):
            address = self.tableWidget_addresstable.item(row, ADDR_COL).text()
            index, length, unicode, zero_terminate = GuiUtils.text_to_valuetype(
                self.tableWidget_addresstable.item(row, TYPE_COL).text())
            table_contents.append([address, index, length, unicode, zero_terminate])
        new_table_contents = GDB_Engine.read_multiple_addresses(table_contents)
        for row, item in enumerate(new_table_contents):
            self.tableWidget_addresstable.setItem(row, VALUE_COL, QTableWidgetItem(str(item)))

    # gets the information from the dialog then adds it to addresstable
    def addaddressmanually_onclick(self):
        manual_address_dialog = ManualAddressDialogForm()
        if manual_address_dialog.exec_():
            description, address, typeofaddress, length, unicode, zero_terminate = manual_address_dialog.get_values()
            self.add_entry_to_addresstable(description=description, address=address, typeofaddress=typeofaddress,
                                           length=length, unicode=unicode,
                                           zero_terminate=zero_terminate)

    def memoryview_onlick(self):
        self.memory_view_window.showMaximized()
        self.memory_view_window.activateWindow()

    def wikibutton_onclick(self):
        webbrowser.open("https://github.com/korcankaraokcu/PINCE/wiki")

    def aboutbutton_onclick(self):
        self.about_widget = AboutWidgetForm()
        self.about_widget.show()

    def settingsbutton_onclick(self):
        settings_dialog = SettingsDialogForm()
        settings_dialog.reset_settings.connect(self.set_default_settings)
        if settings_dialog.exec_():
            self.apply_settings()

    def consolebutton_onclick(self):
        self.console_widget = ConsoleWidgetForm()
        self.console_widget.show()

    def newfirstscan_onclick(self):
        print("Exception test")
        x = 0 / 0
        if self.pushButton_NewFirstScan.text() == "First Scan":
            self.pushButton_NextScan.setEnabled(True)
            self.pushButton_UndoScan.setEnabled(True)
            self.pushButton_NewFirstScan.setText("New Scan")
            return
        if self.pushButton_NewFirstScan.text() == "New Scan":
            self.pushButton_NextScan.setEnabled(False)
            self.pushButton_UndoScan.setEnabled(False)
            self.pushButton_NewFirstScan.setText("First Scan")

    def nextscan_onclick(self):
        # GDB_Engine.send_command('interrupt\nx _start\nc &')  # test
        GDB_Engine.send_command("x/100x _start")
        # t = Thread(target=GDB_Engine.test)  # test
        # t2=Thread(target=test2)
        # t.start()
        # t2.start()
        if self.tableWidget_valuesearchtable.rowCount() <= 0:
            return

    # shows the process select window
    def processbutton_onclick(self):
        self.processwindow = ProcessForm(self)
        self.processwindow.show()

    def delete_address_table_contents(self):
        confirm_dialog = DialogWithButtonsForm(label_text="This will clear the contents of address table\n\tProceed?")
        if confirm_dialog.exec_():
            self.tableWidget_addresstable.setRowCount(0)

    def on_inferior_exit(self):
        GDB_Engine.detach()
        self.on_status_running()
        self.label_SelectedProcess.setText("No Process Selected")
        QMessageBox.information(self, "Warning", "Process has been terminated")
        self.await_exit_thread.start()

    def on_status_stopped(self):
        self.label_SelectedProcess.setStyleSheet("color: red")
        self.label_InferiorStatus.setText("[stopped]")
        self.label_InferiorStatus.setVisible(True)
        self.label_InferiorStatus.setStyleSheet("color: red")
        self.update_address_table_manually()

    def on_status_running(self):
        self.label_SelectedProcess.setStyleSheet("")
        self.label_InferiorStatus.setVisible(False)

    # closes all windows on exit
    def closeEvent(self, event):
        if not GDB_Engine.currentpid == 0:
            GDB_Engine.detach()
        application = QApplication.instance()
        application.closeAllWindows()

    def add_entry_to_addresstable(self, description, address, typeofaddress, length=0, unicode=False,
                                  zero_terminate=True):
        frozen_checkbox = QCheckBox()
        typeofaddress_text = GuiUtils.valuetype_to_text(typeofaddress, length, unicode, zero_terminate)

        # this line lets us take symbols as parameters, pretty rad isn't it?
        address_text = GDB_Engine.convert_symbol_to_address(address)
        if address_text:
            address = address_text
        self.tableWidget_addresstable.setRowCount(self.tableWidget_addresstable.rowCount() + 1)
        currentrow = self.tableWidget_addresstable.rowCount() - 1
        value = GDB_Engine.read_single_address(address, typeofaddress, length, unicode, zero_terminate)
        self.tableWidget_addresstable.setCellWidget(currentrow, FROZEN_COL, frozen_checkbox)
        self.change_address_table_entries(row=currentrow, description=description, address=address,
                                          typeofaddress=typeofaddress_text, value=str(value))
        self.show()  # In case of getting called from elsewhere
        self.activateWindow()

    def on_address_table_double_click(self, index):
        current_row = index.row()
        current_column = index.column()
        if current_column is VALUE_COL:
            value = self.tableWidget_addresstable.item(current_row, VALUE_COL).text()
            value_index = GuiUtils.text_to_index(self.tableWidget_addresstable.item(current_row, TYPE_COL).text())
            dialog = DialogWithButtonsForm(label_text="Enter the new value", hide_line_edit=False,
                                           line_edit_text=value, parse_string=True, value_index=value_index)
            if dialog.exec_():
                table_contents = []
                value_text = dialog.get_values()
                selected_rows = self.tableWidget_addresstable.selectionModel().selectedRows()
                for item in selected_rows:
                    row = item.row()
                    address = self.tableWidget_addresstable.item(row, ADDR_COL).text()
                    value_type = self.tableWidget_addresstable.item(row, TYPE_COL).text()
                    value_index = GuiUtils.text_to_index(value_type)
                    if GuiUtils.text_to_length(value_type) is not -1:
                        unknown_type = SysUtils.parse_string(value_text, value_index)
                        if unknown_type is not None:
                            length = len(unknown_type)
                            self.tableWidget_addresstable.setItem(row, TYPE_COL, QTableWidgetItem(
                                GuiUtils.change_text_length(value_type, length)))
                    table_contents.append([address, value_index])
                GDB_Engine.set_multiple_addresses(table_contents, value_text)
                self.update_address_table_manually()

        elif current_column is DESC_COL:
            description = self.tableWidget_addresstable.item(current_row, DESC_COL).text()
            dialog = DialogWithButtonsForm(label_text="Enter the new description", hide_line_edit=False,
                                           line_edit_text=description)
            if dialog.exec_():
                description_text = dialog.get_values()
                selected_rows = self.tableWidget_addresstable.selectionModel().selectedRows()
                for item in selected_rows:
                    self.tableWidget_addresstable.setItem(item.row(), DESC_COL, QTableWidgetItem(description_text))
        elif current_column is ADDR_COL or current_column is TYPE_COL:
            description, address, value_type = self.read_address_table_entries(row=current_row)
            index, length, unicode, zero_terminate = GuiUtils.text_to_valuetype(value_type)
            manual_address_dialog = ManualAddressDialogForm(description=description, address=address, index=index,
                                                            length=length, unicode=unicode,
                                                            zero_terminate=zero_terminate)
            if manual_address_dialog.exec_():
                description, address, typeofaddress, length, unicode, zero_terminate = manual_address_dialog.get_values()
                typeofaddress_text = GuiUtils.valuetype_to_text(value_index=typeofaddress, length=length,
                                                                is_unicode=unicode,
                                                                zero_terminate=zero_terminate)
                address_text = GDB_Engine.convert_symbol_to_address(address)
                if address_text:
                    address = address_text
                value = GDB_Engine.read_single_address(address=address, value_index=typeofaddress,
                                                       length=length, is_unicode=unicode,
                                                       zero_terminate=zero_terminate)
                self.change_address_table_entries(row=current_row, description=description, address=address,
                                                  typeofaddress=typeofaddress_text, value=str(value))

    # Changes the column values of the given row
    def change_address_table_entries(self, row, description="", address="", typeofaddress="", value=""):
        self.tableWidget_addresstable.setItem(row, DESC_COL, QTableWidgetItem(description))
        self.tableWidget_addresstable.setItem(row, ADDR_COL, QTableWidgetItem(address))
        self.tableWidget_addresstable.setItem(row, TYPE_COL, QTableWidgetItem(typeofaddress))
        self.tableWidget_addresstable.setItem(row, VALUE_COL, QTableWidgetItem(value))

    # Returns the column values of the given row
    def read_address_table_entries(self, row):
        description = self.tableWidget_addresstable.item(row, DESC_COL).text()
        address = self.tableWidget_addresstable.item(row, ADDR_COL).text()
        value_type = self.tableWidget_addresstable.item(row, TYPE_COL).text()
        return description, address, value_type


# process select window
class ProcessForm(QMainWindow, ProcessWindow):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setupUi(self)
        GuiUtils.center_to_parent(self)
        # self.loadingwidget = LoadingWidgetForm()
        processlist = SysUtils.get_process_list()
        self.refresh_process_table(self.processtable, processlist)
        self.pushButton_Close.clicked.connect(self.pushbutton_close_onclick)
        self.pushButton_Open.clicked.connect(self.pushbutton_open_onclick)
        self.lineEdit_searchprocess.textChanged.connect(self.generate_new_list)
        self.processtable.itemDoubleClicked.connect(self.pushbutton_open_onclick)

    # refreshes process list
    def generate_new_list(self):
        text = self.lineEdit_searchprocess.text()
        processlist = SysUtils.search_in_processes_by_name(text)
        self.refresh_process_table(self.processtable, processlist)

    # closes the window whenever ESC key is pressed
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close()

    # lists currently working processes to table
    def refresh_process_table(self, tablewidget, processlist):
        tablewidget.setRowCount(0)
        tablewidget.setRowCount(len(processlist))
        for i, row in enumerate(processlist):
            tablewidget.setItem(i, 0, QTableWidgetItem(str(row.pid)))
            tablewidget.setItem(i, 1, QTableWidgetItem(row.username()))
            tablewidget.setItem(i, 2, QTableWidgetItem(row.name()))

    # self-explanatory
    def pushbutton_close_onclick(self):
        self.close()

    # gets the pid out of the selection to attach
    def pushbutton_open_onclick(self):
        currentitem = self.processtable.item(self.processtable.currentIndex().row(), 0)
        if currentitem is None:
            QMessageBox.information(self, "Error", "Please select a process first")
        else:
            pid = int(currentitem.text())
            if not SysUtils.is_process_valid(pid):
                QMessageBox.information(self, "Error", "Selected process is not valid")
                return
            if pid == selfpid:
                QMessageBox.information(self, "Error", "What the fuck are you trying to do?")  # planned easter egg
                return
            if pid == GDB_Engine.currentpid:
                QMessageBox.information(self, "Error", "You're debugging this process already")
                return
            tracedby = SysUtils.is_traced(pid)
            if tracedby:
                QMessageBox.information(self, "Error",
                                        "That process is already being traced by " + tracedby + ", could not attach to the process")
                return
            self.setCursor(QCursor(Qt.WaitCursor))
            # self.setCentralWidget(self.loadingwidget)
            # self.loadingwidget.show()
            print("processing")  # loading_widget start
            result = GDB_Engine.can_attach(pid)
            if not result:
                print("done")  # loading_widget finish
                QMessageBox.information(self, "Error", "Permission denied, could not attach to the process")
                return
            if not GDB_Engine.currentpid == 0:
                GDB_Engine.detach()
            GDB_Engine.attach(pid)
            p = SysUtils.get_process_information(GDB_Engine.currentpid)
            self.parent().label_SelectedProcess.setText(str(p.pid) + " - " + p.name())
            self.parent().QWidget_Toolbox.setEnabled(True)
            self.parent().pushButton_NextScan.setEnabled(False)
            self.parent().pushButton_UndoScan.setEnabled(False)
            readable_only, writeable, executable, readable = SysUtils.get_memory_regions_by_perms(
                GDB_Engine.currentpid)  # test
            SysUtils.exclude_system_memory_regions(readable)
            print(len(readable))
            print("done")  # loading_widget finish
            # self.loadingwidget.hide()
            self.close()


# Add Address Manually Dialog
class ManualAddressDialogForm(QDialog, ManualAddressDialog):
    def __init__(self, parent=None, description="No Description", address="0x", index=INDEX_4BYTES, length=10,
                 unicode=False,
                 zero_terminate=True):
        super().__init__(parent=parent)
        self.setupUi(self)
        self.lineEdit_description.setText(description)
        self.lineEdit_address.setText(address)
        self.comboBox_ValueType.setCurrentIndex(index)
        if self.comboBox_ValueType.currentIndex() is INDEX_STRING:
            self.label_length.show()
            self.lineEdit_length.show()
            try:
                length = str(length)
            except:
                length = "10"
            self.lineEdit_length.setText(length)
            self.checkBox_Unicode.show()
            self.checkBox_Unicode.setChecked(unicode)
            self.checkBox_zeroterminate.show()
            self.checkBox_zeroterminate.setChecked(zero_terminate)
        elif self.comboBox_ValueType.currentIndex() is INDEX_AOB:
            self.label_length.show()
            self.lineEdit_length.show()
            try:
                length = str(length)
            except:
                length = "10"
            self.lineEdit_length.setText(length)
            self.checkBox_Unicode.hide()
            self.checkBox_zeroterminate.hide()
        else:
            self.label_length.hide()
            self.lineEdit_length.hide()
            self.checkBox_Unicode.hide()
            self.checkBox_zeroterminate.hide()
        self.comboBox_ValueType.currentIndexChanged.connect(self.valuetype_on_current_index_change)
        self.lineEdit_length.textChanged.connect(self.length_text_on_change)
        self.checkBox_Unicode.stateChanged.connect(self.unicode_box_on_check)
        self.checkBox_zeroterminate.stateChanged.connect(self.zeroterminate_box_on_check)
        self.update_needed = True
        self.lineEdit_address.textChanged.connect(self.address_on_change)
        self.update_thread = Thread(target=self.update_value_of_address)
        self.update_thread.daemon = True
        self.update_thread.start()

    # constantly updates the value of the address
    def update_value_of_address(self):
        while not self.update_thread._is_stopped:
            sleep(0.01)
            if self.update_needed:
                self.update_needed = False
                address = self.lineEdit_address.text()
                address_type = self.comboBox_ValueType.currentIndex()
                if address_type is INDEX_AOB:
                    length = self.lineEdit_length.text()
                    self.label_valueofaddress.setText(
                        GDB_Engine.read_single_address_by_expression(address, address_type, length))
                elif address_type is INDEX_STRING:
                    length = self.lineEdit_length.text()
                    is_unicode = self.checkBox_Unicode.isChecked()
                    is_zeroterminate = self.checkBox_zeroterminate.isChecked()
                    self.label_valueofaddress.setText(
                        GDB_Engine.read_single_address_by_expression(address, address_type, length, is_unicode,
                                                                     is_zeroterminate))
                else:
                    self.label_valueofaddress.setText(
                        GDB_Engine.read_single_address_by_expression(address, address_type))

    def address_on_change(self):
        self.update_needed = True

    def length_text_on_change(self):
        self.update_needed = True

    def unicode_box_on_check(self):
        self.update_needed = True

    def zeroterminate_box_on_check(self):
        self.update_needed = True

    def valuetype_on_current_index_change(self):
        if self.comboBox_ValueType.currentIndex() is INDEX_STRING:
            self.label_length.show()
            self.lineEdit_length.show()
            self.checkBox_Unicode.show()
            self.checkBox_zeroterminate.show()
        elif self.comboBox_ValueType.currentIndex() is INDEX_AOB:
            self.label_length.show()
            self.lineEdit_length.show()
            self.checkBox_Unicode.hide()
            self.checkBox_zeroterminate.hide()
        else:
            self.label_length.hide()
            self.lineEdit_length.hide()
            self.checkBox_Unicode.hide()
            self.checkBox_zeroterminate.hide()
        self.update_needed = True

    def reject(self):
        self.update_thread._is_stopped = True
        super(ManualAddressDialogForm, self).reject()

    def accept(self):
        if self.label_length.isVisible():
            length = self.lineEdit_length.text()
            try:
                length = int(length)
            except:
                QMessageBox.information(self, "Error", "Length is not valid")
                return
            if length < 0:
                QMessageBox.information(self, "Error", "Length cannot be smaller than 0")
                return
        self.update_thread._is_stopped = True
        super(ManualAddressDialogForm, self).accept()

    def get_values(self):
        description = self.lineEdit_description.text()
        address = self.lineEdit_address.text()
        length = self.lineEdit_length.text()
        try:
            length = int(length)
        except:
            length = 0
        unicode = False
        zero_terminate = False
        if self.checkBox_Unicode.isChecked():
            unicode = True
        if self.checkBox_zeroterminate.isChecked():
            zero_terminate = True
        typeofaddress = self.comboBox_ValueType.currentIndex()
        return description, address, typeofaddress, length, unicode, zero_terminate


# FIXME: the gif in qlabel won't update itself, also the design of this class is generally shitty
# FIXME: this class is temporary and buggy, so all implementations of this shit should be fixed as soon as this class gets fixed
# I designed(sorry) this as a widget, but you can transform it to anything if it's going to fix the gif problem
class LoadingWidgetForm(QWidget, LoadingWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setupUi(self)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        pince_directory = SysUtils.get_current_script_directory()
        self.movie = QMovie(pince_directory + "/media/loading_widget_gondola.gif", QByteArray())
        self.label_Animated.setMovie(self.movie)
        self.movie.setScaledSize(QSize(50, 50))
        self.movie.setCacheMode(QMovie.CacheAll)
        self.movie.setSpeed(100)
        self.movie.start()
        self.not_finished = True
        # self.update_thread = Thread(target=self.update_widget)
        # self.update_thread.daemon = True
        # self.movie.frameChanged.connect(self.update_shit)
        # self.loading_thread = LoadingWindowThread()
        # self.loading_thread.update_needed.connect(QApplication.processEvents)

    def showEvent(self, QShowEvent):  # from here
        QApplication.processEvents()
        # self.update_thread.start()

    def hideEvent(self, QHideEvent):
        self.not_finished = False

    def update_widget(self):
        while self.not_finished:
            QApplication.processEvents()

    def change_text(self, text):
        self.label_StatusText.setText(text)
        QApplication.processEvents()


class LoadingWindowThread(QThread):
    not_finished = True
    update_needed = pyqtSignal()

    def run(self):
        while self.not_finished:
            sleep(0.001)
            self.update_needed.emit()  # to here should be reworked


class DialogWithButtonsForm(QDialog, DialogWithButtons):
    def __init__(self, parent=None, label_text="", hide_line_edit=True, line_edit_text="", parse_string=False,
                 value_index=INDEX_4BYTES):
        super().__init__(parent=parent)
        self.setupUi(self)
        self.parse_string = parse_string
        self.value_index = value_index
        label_text = str(label_text)
        self.label.setText(label_text)
        if hide_line_edit:
            self.lineEdit.hide()
        else:
            line_edit_text = str(line_edit_text)
            self.lineEdit.setText(line_edit_text)

    def get_values(self):
        line_edit_text = self.lineEdit.text()
        return line_edit_text

    def accept(self):
        if self.parse_string:
            string = self.lineEdit.text()
            if SysUtils.parse_string(string, self.value_index) is None:
                QMessageBox.information(self, "Error", "Can't parse the input")
                return
        super(DialogWithButtonsForm, self).accept()


class SettingsDialogForm(QDialog, SettingsDialog):
    reset_settings = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setupUi(self)

        # Yet another retarded hack, thanks to pyuic5 not supporting QKeySequenceEdit
        self.keySequenceEdit = QKeySequenceEdit()
        self.verticalLayout_Hotkey.addWidget(self.keySequenceEdit)
        self.listWidget_Options.currentRowChanged.connect(self.change_display)
        self.listWidget_Functions.currentRowChanged.connect(self.on_hotkey_index_change)
        self.keySequenceEdit.keySequenceChanged.connect(self.on_key_sequence_change)
        self.pushButton_ClearHotkey.clicked.connect(self.on_clear_button_pressed)
        self.pushButton_ResetSettings.clicked.connect(self.on_reset_button_pressed)
        self.checkBox_AutoUpdateAddressTable.stateChanged.connect(self.on_checkbox_auto_update_address_table_pressed)
        self.config_gui()

    def accept(self):
        try:
            current_table_update_interval = float(self.lineEdit_UpdateInterval.text())
        except:
            QMessageBox.information(self, "Error", "Update interval must be a float")
            return
        try:
            current_insturctions_shown = int(self.lineEdit_InstructionsPerScroll.text())
        except:
            QMessageBox.information(self, "Error", "Instruction count must be an integer")
            return
        if current_insturctions_shown < 1:
            QMessageBox.information(self, "Error", "Instruction count cannot be lower than 1" +
                                    "\nIt would be retarded anyways, wouldn't it?")
            return
        if current_table_update_interval < 0:
            QMessageBox.information(self, "Error", "Update interval cannot be a negative number")
            return
        elif current_table_update_interval == 0:

            # Easter egg #2
            if not DialogWithButtonsForm(label_text="You are asking for it, aren't you?").exec_():
                return
        elif current_table_update_interval < 0.1:
            if not DialogWithButtonsForm(label_text="Update interval should be bigger than 0.1 seconds" +
                    "\nSetting update interval less than 0.1 seconds may cause slowness" +
                    "\n\tProceed?").exec_():
                return
        self.settings.setValue("General/auto_update_address_table", self.checkBox_AutoUpdateAddressTable.isChecked())
        self.settings.setValue("General/address_table_update_interval", current_table_update_interval)
        self.settings.setValue("Hotkeys/pause", self.pause_hotkey)
        self.settings.setValue("Hotkeys/continue", self.continue_hotkey)
        if self.radioButton_SimpleDLopenCall.isChecked():
            injection_method = SIMPLE_DLOPEN_CALL
        elif self.radioButton_AdvancedInjection.isChecked():
            injection_method = ADVANCED_INJECTION
        self.settings.setValue("CodeInjection/code_injection_method", injection_method)
        self.settings.setValue("Disassemble/bring_disassemble_to_front",
                               self.checkBox_BringDisassembleToFront.isChecked())
        self.settings.setValue("Disassemble/instructions_per_scroll", current_insturctions_shown)
        super(SettingsDialogForm, self).accept()

    def config_gui(self):
        self.settings = QSettings()
        self.checkBox_AutoUpdateAddressTable.setChecked(
            self.settings.value("General/auto_update_address_table", type=bool))
        self.lineEdit_UpdateInterval.setText(
            str(self.settings.value("General/address_table_update_interval", type=float)))
        self.pause_hotkey = self.settings.value("Hotkeys/pause")
        self.continue_hotkey = self.settings.value("Hotkeys/continue")
        injection_method = self.settings.value("CodeInjection/code_injection_method", type=int)
        if injection_method == SIMPLE_DLOPEN_CALL:
            self.radioButton_SimpleDLopenCall.setChecked(True)
        elif injection_method == ADVANCED_INJECTION:
            self.radioButton_AdvancedInjection.setChecked(True)
        self.checkBox_BringDisassembleToFront.setChecked(
            self.settings.value("Disassemble/bring_disassemble_to_front", type=bool))
        self.lineEdit_InstructionsPerScroll.setText(
            str(self.settings.value("Disassemble/instructions_per_scroll", type=int)))

    def change_display(self, index):
        self.stackedWidget.setCurrentIndex(index)

    def on_hotkey_index_change(self, index):
        if index is 0:
            self.keySequenceEdit.setKeySequence(self.pause_hotkey)
        elif index is 1:
            self.keySequenceEdit.setKeySequence(self.continue_hotkey)

    def on_key_sequence_change(self):
        current_index = self.listWidget_Functions.currentIndex().row()
        if current_index is 0:
            self.pause_hotkey = self.keySequenceEdit.keySequence().toString()
        elif current_index is 1:
            self.continue_hotkey = self.keySequenceEdit.keySequence().toString()

    def on_clear_button_pressed(self):
        self.keySequenceEdit.clear()

    def on_reset_button_pressed(self):
        confirm_dialog = DialogWithButtonsForm(label_text="This will reset to the default settings\n\tProceed?")
        if confirm_dialog.exec_():
            self.reset_settings.emit()
        else:
            return
        self.config_gui()

    def on_checkbox_auto_update_address_table_pressed(self):
        if self.checkBox_AutoUpdateAddressTable.isChecked():
            self.QWidget_UpdateInterval.setEnabled(True)
        else:
            self.QWidget_UpdateInterval.setEnabled(False)


class ConsoleWidgetForm(QWidget, ConsoleWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setupUi(self)
        GuiUtils.center(self)
        self.await_async_output_thread = AwaitAsyncOutput()
        self.await_async_output_thread.async_output_ready.connect(self.on_async_output)
        self.await_async_output_thread.start()
        self.pushButton_Send.clicked.connect(self.communicate)
        self.pushButton_SendCtrl.clicked.connect(lambda: self.communicate(control=True))
        self.shortcut_send = QShortcut(QKeySequence("Return"), self)
        self.shortcut_send.activated.connect(self.communicate)
        self.shortcut_send_ctrl = QShortcut(QKeySequence("Ctrl+C"), self)
        self.shortcut_send_ctrl.activated.connect(lambda: self.communicate(control=True))
        self.textBrowser.append("Hotkeys:")
        self.textBrowser.append("--------------------")
        self.textBrowser.append("Send=Enter         |\nSend ctrl+c=Ctrl+C |")
        self.textBrowser.append("--------------------")
        self.textBrowser.append("Commands:")
        self.textBrowser.append("---------------------------")
        self.textBrowser.append("/clear: Clear the console |")
        self.textBrowser.append("---------------------------")
        self.textBrowser.append("You can change the output mode from bottom right")
        self.textBrowser.append("Note: Changing output mode only affects commands sent. Any other " +
                                "output coming from external sources(e.g async output) will be shown in MI format")

    def communicate(self, control=False):
        if control:
            console_input = "/Ctrl+C"
        else:
            console_input = self.lineEdit.text()
        if console_input.lower() == "/clear":
            self.textBrowser.clear()
            console_output = "Cleared"
        elif console_input.strip().lower().startswith("-"):
            console_output = "GDB/MI commands aren't supported yet"
        elif console_input.strip().lower() == "q" or console_input.strip().lower() == "quit":
            console_output = "pls don't"
        else:
            if not control:
                if self.radioButton_CLI.isChecked():
                    console_output = GDB_Engine.send_command(console_input, cli_output=True)
                else:
                    console_output = GDB_Engine.send_command(console_input)
                if not console_output:
                    console_output = "Inferior is running"
            else:
                GDB_Engine.interrupt_inferior()
                console_output = "STOPPED"
        self.textBrowser.append("-->" + console_input)
        self.textBrowser.append(console_output)
        self.textBrowser.verticalScrollBar().setValue(self.textBrowser.verticalScrollBar().maximum())

    def on_async_output(self):
        self.textBrowser.append(GDB_Engine.gdb_async_output)
        self.textBrowser.verticalScrollBar().setValue(self.textBrowser.verticalScrollBar().maximum())


class AboutWidgetForm(QTabWidget, AboutWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setupUi(self)
        GuiUtils.center(self)
        license_text = open("COPYING").read()
        authors_text = open("AUTHORS").read()
        thanks_text = open("THANKS").read()
        self.textBrowser_License.setPlainText(license_text)
        self.textBrowser_Contributors.append(
            "This is only a placeholder, this section may look different when the project finishes" +
            "\nIn fact, something like a demo-scene for here would look absolutely fabulous <:")
        self.textBrowser_Contributors.append("\n########")
        self.textBrowser_Contributors.append("#AUTHORS#")
        self.textBrowser_Contributors.append("########\n")
        self.textBrowser_Contributors.append(authors_text)
        self.textBrowser_Contributors.append("\n#######")
        self.textBrowser_Contributors.append("#THANKS#")
        self.textBrowser_Contributors.append("#######\n")
        self.textBrowser_Contributors.append(thanks_text)


class MemoryViewWindowForm(QMainWindow, MemoryViewWindow):
    process_stopped = pyqtSignal()
    process_running = pyqtSignal()

    # TODO: Change this nonsense when the huge refactorization happens
    address_added = pyqtSignal(object, object, object, object, object, object)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setupUi(self)
        GuiUtils.center(self)
        self.process_stopped.connect(self.on_process_stop)
        self.process_running.connect(self.on_process_running)
        self.initialize_disassemble_view()
        self.initialize_register_view()
        self.initialize_stack_view()
        self.initialize_hex_view()

        self.actionBookmarks.triggered.connect(self.on_ViewBookmarks_triggered)
        self.actionStackTrace_Info.triggered.connect(self.on_stacktrace_info_triggered)
        self.actionInject_so_file.triggered.connect(self.on_inject_so_file_triggered)

        self.splitter_Disassemble_Registers.setStretchFactor(0, 1)
        self.widget_StackView.resize(420, self.widget_StackView.height())  # blaze it
        self.widget_Registers.resize(330, self.widget_Registers.height())

    def initialize_register_view(self):
        self.pushButton_ShowFloatRegisters.clicked.connect(self.on_show_float_registers_button_clicked)

    def initialize_stack_view(self):
        self.tableWidget_StackTrace.setColumnWidth(STACKTRACE_RETURN_ADDRESS_COL, 350)

        self.tableWidget_Stack.contextMenuEvent = self.tableWidget_Stack_context_menu_event
        self.tableWidget_StackTrace.contextMenuEvent = self.tableWidget_StackTrace_context_menu_event
        self.tableWidget_StackTrace.itemDoubleClicked.connect(self.tableWidget_StackTrace_double_click)

    def initialize_disassemble_view(self):
        self.disassemble_currently_displayed_address = "0x00400000"
        self.widget_Disassemble.wheelEvent = self.widget_Disassemble_wheel_event

        self.tableWidget_Disassemble.wheelEvent = QEvent.ignore
        self.verticalScrollBar_Disassemble.wheelEvent = QEvent.ignore

        GuiUtils.center_scroll_bar(self.verticalScrollBar_Disassemble)
        self.verticalScrollBar_Disassemble.mouseReleaseEvent = self.verticalScrollBar_Disassemble_mouse_release_event

        self.disassemble_scroll_bar_timer = QTimer()
        self.disassemble_scroll_bar_timer.setInterval(100)
        self.disassemble_scroll_bar_timer.timeout.connect(self.check_disassemble_scrollbar)
        self.disassemble_scroll_bar_timer.start()

        # Format: [address1, address2, ...]
        self.tableWidget_Disassemble.travel_history = []

        # Format: {address1:comment1,address2:comment2, ...}
        self.tableWidget_Disassemble.bookmarks = {}

        self.tableWidget_Disassemble.keyPressEvent = self.tableWidget_Disassemble_key_press_event
        self.tableWidget_Disassemble.contextMenuEvent = self.tableWidget_Disassemble_context_menu_event

        self.tableWidget_Disassemble.itemDoubleClicked.connect(self.on_disassemble_double_click)

    def initialize_hex_view(self):
        self.hex_view_currently_displayed_address = 0x00400000
        self.widget_HexView.wheelEvent = self.widget_HexView_wheel_event

        self.widget_HexView.contextMenuEvent = self.widget_HexView_context_menu_event

        self.verticalScrollBar_HexView.wheelEvent = QEvent.ignore
        self.listWidget_HexView_Address.wheelEvent = QEvent.ignore
        self.scrollArea_Hex.keyPressEvent = QEvent.ignore
        self.listWidget_HexView_Address.setAutoScroll(False)
        self.listWidget_HexView_Address.setStyleSheet("QListWidget {background-color: transparent;}")

        self.hex_model = QHexModel(HEX_VIEW_ROW_COUNT, HEX_VIEW_COL_COUNT)
        self.ascii_model = QAsciiModel(HEX_VIEW_ROW_COUNT, HEX_VIEW_COL_COUNT)
        self.tableView_HexView_Hex.setModel(self.hex_model)
        self.tableView_HexView_Ascii.setModel(self.ascii_model)

        self.tableView_HexView_Hex.selectionModel().currentChanged.connect(self.on_hex_view_current_changed)
        self.tableView_HexView_Ascii.selectionModel().currentChanged.connect(self.on_ascii_view_current_changed)

        self.scrollArea_Hex.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollArea_Hex.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.listWidget_HexView_Address.setVerticalScrollBarPolicy((Qt.ScrollBarAlwaysOff))
        self.listWidget_HexView_Address.setHorizontalScrollBarPolicy((Qt.ScrollBarAlwaysOff))

        GuiUtils.center_scroll_bar(self.verticalScrollBar_HexView)
        self.hex_view_scroll_bar_timer = QTimer()
        self.hex_view_scroll_bar_timer.setInterval(100)
        self.hex_view_scroll_bar_timer.timeout.connect(self.check_hex_view_scrollbar)
        self.hex_view_scroll_bar_timer.start()
        self.verticalScrollBar_HexView.mouseReleaseEvent = self.verticalScrollBar_HexView_mouse_release_event

    def widget_HexView_context_menu_event(self, event):
        menu = QMenu()
        go_to = menu.addAction("Go to expression")
        menu.addSeparator()
        add_address = menu.addAction("Add this address to address list")
        menu.addSeparator()
        refresh = menu.addAction("Refresh")
        font_size = self.widget_HexView.font().pointSize()
        menu.setStyleSheet("font-size: " + str(font_size) + "pt;")
        current_address = hex(self.hex_view_currently_displayed_address)
        action = menu.exec_(event.globalPos())
        if action == go_to:
            go_to_dialog = DialogWithButtonsForm(label_text="Enter the expression", hide_line_edit=False,
                                                 line_edit_text=current_address)
            if go_to_dialog.exec_():
                expression = go_to_dialog.get_values()
                dest_address = GDB_Engine.convert_symbol_to_address(expression)
                if dest_address is None:
                    QMessageBox.information(self, "Error", "Cannot access memory at expression " + expression)
                    return
                self.hex_dump_address(int(dest_address, 16))
        elif action == add_address:
            selected_address = self.hex_view_currently_displayed_address + self.tableView_HexView_Hex.get_current_offset()
            manual_address_dialog = ManualAddressDialogForm(address=hex(selected_address), index=INDEX_AOB)
            if manual_address_dialog.exec_():
                description, address, typeofaddress, length, unicode, zero_terminate = manual_address_dialog.get_values()
                self.address_added.emit(description, address, typeofaddress, length, unicode, zero_terminate)
        elif action == refresh:
            self.hex_dump_address(self.hex_view_currently_displayed_address)

    def verticalScrollBar_HexView_mouse_release_event(self, event):
        GuiUtils.center_scroll_bar(self.verticalScrollBar_HexView)

    def verticalScrollBar_Disassemble_mouse_release_event(self, event):
        GuiUtils.center_scroll_bar(self.verticalScrollBar_Disassemble)

    def check_hex_view_scrollbar(self):
        if GDB_Engine.inferior_status != INFERIOR_STOPPED:
            return
        maximum = self.verticalScrollBar_HexView.maximum()
        minimum = self.verticalScrollBar_HexView.minimum()
        midst = (maximum + minimum) / 2
        current_value = self.verticalScrollBar_HexView.value()
        if midst - 10 < current_value < midst + 10:
            return
        current_address = self.hex_view_currently_displayed_address
        if current_value < midst:
            next_address = current_address - 0x40
        else:
            next_address = current_address + 0x40
        self.hex_dump_address(next_address)

    def check_disassemble_scrollbar(self):
        if GDB_Engine.inferior_status != INFERIOR_STOPPED:
            return
        maximum = self.verticalScrollBar_Disassemble.maximum()
        minimum = self.verticalScrollBar_Disassemble.minimum()
        midst = (maximum + minimum) / 2
        current_value = self.verticalScrollBar_Disassemble.value()
        if midst - 10 < current_value < midst + 10:
            return
        current_address = self.disassemble_currently_displayed_address
        if current_value < midst:
            next_address = GDB_Engine.find_address_of_closest_instruction(current_address, instructions_per_scroll,
                                                                          "previous")
        else:
            next_address = GDB_Engine.find_address_of_closest_instruction(current_address, instructions_per_scroll,
                                                                          "next")
        self.disassemble_expression(next_address)

    def on_hex_view_current_changed(self, QModelIndex_current):
        self.tableView_HexView_Ascii.selectionModel().setCurrentIndex(QModelIndex_current,
                                                                      QItemSelectionModel.ClearAndSelect)
        self.listWidget_HexView_Address.setCurrentRow(QModelIndex_current.row())

    def on_ascii_view_current_changed(self, QModelIndex_current):
        self.tableView_HexView_Hex.selectionModel().setCurrentIndex(QModelIndex_current,
                                                                    QItemSelectionModel.ClearAndSelect)
        self.listWidget_HexView_Address.setCurrentRow(QModelIndex_current.row())

    def hex_dump_address(self, int_address, offset=HEX_VIEW_ROW_COUNT * HEX_VIEW_COL_COUNT):
        information = SysUtils.get_region_info(GDB_Engine.currentpid, int_address)
        if information is not None:
            self.label_HexView_Information.setText(
                "Protection:" + information.region.perms + " | Base:" + information.start + "-" + information.end)
        else:
            self.label_HexView_Information.setText("This region is invalid")
        self.listWidget_HexView_Address.clear()
        for current_offset in range(HEX_VIEW_ROW_COUNT):
            self.listWidget_HexView_Address.addItem(hex(int_address + current_offset * 16))
        listwidget_column_size = self.listWidget_HexView_Address.sizeHintForColumn(0) + 10
        self.listWidget_HexView_Address.setMaximumWidth(listwidget_column_size)
        self.listWidget_HexView_Address.setMinimumWidth(listwidget_column_size)
        hex_list = GDB_Engine.hex_dump(int_address, offset)
        self.hex_model.refresh(hex_list)
        self.ascii_model.refresh(hex_list)
        self.hex_view_currently_displayed_address = int_address

    def refresh_hex_view(self):
        if self.listWidget_HexView_Address.count() == 0:
            # ELF header usually starts at address 0x00400000
            self.hex_dump_address(0x00400000)
            self.tableView_HexView_Hex.resize_to_contents()
            self.tableView_HexView_Ascii.resize_to_contents()
        else:
            self.hex_dump_address(self.hex_view_currently_displayed_address)

    # offset can also be an address as hex str
    def disassemble_expression(self, expression, offset="+200", append_to_travel_history=False):
        disas_data = GDB_Engine.disassemble(expression, offset)
        if not disas_data:
            QMessageBox.information(self, "Error", "Cannot access memory at expression " + expression)
            return
        program_counter = GDB_Engine.convert_symbol_to_address("$pc", check=False)
        program_counter_int = int(program_counter, 16)
        row_of_pc = False
        rows_of_encountered_bookmarks_list = []

        # TODO: Change this nonsense when the huge refactorization happens
        current_first_address = SysUtils.extract_address(disas_data[0][0])  # address of first list entry
        try:
            previous_first_address = SysUtils.extract_address(
                self.tableWidget_Disassemble.item(0, DISAS_ADDR_COL).text())
        except AttributeError:
            previous_first_address = current_first_address

        self.tableWidget_Disassemble.setRowCount(0)
        self.tableWidget_Disassemble.setRowCount(len(disas_data))
        for row, item in enumerate(disas_data):
            comment = ""
            current_address = int(SysUtils.extract_address(item[0]), 16)
            if current_address == program_counter_int:
                item[0] = ">>>" + item[0]
                row_of_pc = row
            for bookmark_item in self.tableWidget_Disassemble.bookmarks.keys():
                if current_address == bookmark_item:
                    rows_of_encountered_bookmarks_list.append(row)
                    item[0] = "(M)" + item[0]
                    comment = self.tableWidget_Disassemble.bookmarks[bookmark_item]
                    break
            self.tableWidget_Disassemble.setItem(row, DISAS_ADDR_COL, QTableWidgetItem(item[0]))
            self.tableWidget_Disassemble.setItem(row, DISAS_BYTES_COL, QTableWidgetItem(item[1]))
            self.tableWidget_Disassemble.setItem(row, DISAS_OPCODES_COL, QTableWidgetItem(item[2]))
            self.tableWidget_Disassemble.setItem(row, DISAS_COMMENT_COL, QTableWidgetItem(comment))
        self.handle_colours(row_of_pc, rows_of_encountered_bookmarks_list)
        self.tableWidget_Disassemble.resizeColumnsToContents()
        self.tableWidget_Disassemble.horizontalHeader().setStretchLastSection(True)

        # We append the old record to travel history as last action because we wouldn't like to see unnecessary
        # addresses in travel history if any error occurs while displaying the next location
        if append_to_travel_history:
            self.tableWidget_Disassemble.travel_history.append(previous_first_address)
        self.disassemble_currently_displayed_address = current_first_address

    # Set colour of a row if a specific address is encountered(e.g $pc, a bookmarked address etc.)
    def handle_colours(self, row_of_pc, encountered_bookmark_list):
        if row_of_pc:
            self.set_row_colour(row_of_pc, PC_COLOUR)
        if encountered_bookmark_list:
            for encountered_row in encountered_bookmark_list:
                self.set_row_colour(encountered_row, BOOKMARK_COLOUR)

    # color parameter should be Qt.colour
    def set_row_colour(self, row, colour):
        for item in range(self.tableWidget_Disassemble.columnCount()):
            self.tableWidget_Disassemble.item(row, item).setData(Qt.BackgroundColorRole, QColor(colour))

    def on_process_stop(self):
        time0 = time()
        thread_info = GDB_Engine.get_current_thread_information()
        self.setWindowTitle("Memory Viewer - Currently Debugging Thread " + thread_info)
        self.disassemble_expression("$pc")
        self.update_registers()
        if self.stackedWidget_StackScreens.currentWidget() == self.StackTrace:
            self.update_stacktrace()
        elif self.stackedWidget_StackScreens.currentWidget() == self.Stack:
            self.update_stack()
        self.refresh_hex_view()
        self.showMaximized()
        if bring_disassemble_to_front:
            self.activateWindow()
        try:
            if self.stacktrace_info_widget.isVisible():
                self.stacktrace_info_widget.update_stacktrace()
        except AttributeError:
            pass
        try:
            if self.float_registers_widget.isVisible():
                self.float_registers_widget.update_registers()
        except AttributeError:
            pass
        time1 = time()
        print("UPDATED MEMORYVIEW IN:" + str(time1 - time0))

    def on_process_running(self):
        self.setWindowTitle("Memory Viewer - Running")

    def update_registers(self):
        registers = GDB_Engine.read_registers()
        if GDB_Engine.inferior_arch == ARCH_64:
            self.stackedWidget.setCurrentWidget(self.registers_64)
            self.RAX.set_value(registers["rax"])
            self.RBX.set_value(registers["rbx"])
            self.RCX.set_value(registers["rcx"])
            self.RDX.set_value(registers["rdx"])
            self.RSI.set_value(registers["rsi"])
            self.RDI.set_value(registers["rdi"])
            self.RBP.set_value(registers["rbp"])
            self.RSP.set_value(registers["rsp"])
            self.RIP.set_value(registers["rip"])
            self.R8.set_value(registers["r8"])
            self.R9.set_value(registers["r9"])
            self.R10.set_value(registers["r10"])
            self.R11.set_value(registers["r11"])
            self.R12.set_value(registers["r12"])
            self.R13.set_value(registers["r13"])
            self.R14.set_value(registers["r14"])
            self.R15.set_value(registers["r15"])
        elif GDB_Engine.inferior_arch == ARCH_32:
            self.stackedWidget.setCurrentWidget(self.registers_32)
            self.EAX.set_value(registers["eax"])
            self.EBX.set_value(registers["ebx"])
            self.ECX.set_value(registers["ecx"])
            self.EDX.set_value(registers["edx"])
            self.ESI.set_value(registers["esi"])
            self.EDI.set_value(registers["edi"])
            self.EBP.set_value(registers["ebp"])
            self.ESP.set_value(registers["esp"])
            self.EIP.set_value(registers["eip"])
        self.CF.set_value(registers["cf"])
        self.PF.set_value(registers["pf"])
        self.AF.set_value(registers["af"])
        self.ZF.set_value(registers["zf"])
        self.SF.set_value(registers["sf"])
        self.TF.set_value(registers["tf"])
        self.IF.set_value(registers["if"])
        self.DF.set_value(registers["df"])
        self.OF.set_value(registers["of"])
        self.CS.set_value(registers["cs"])
        self.SS.set_value(registers["ss"])
        self.DS.set_value(registers["ds"])
        self.ES.set_value(registers["es"])
        self.GS.set_value(registers["gs"])
        self.FS.set_value(registers["fs"])

    def update_stacktrace(self):
        stack_trace_info = GDB_Engine.get_stacktrace_info()
        self.tableWidget_StackTrace.setRowCount(0)
        self.tableWidget_StackTrace.setRowCount(len(stack_trace_info))
        for row, item in enumerate(stack_trace_info):
            self.tableWidget_StackTrace.setItem(row, STACKTRACE_RETURN_ADDRESS_COL, QTableWidgetItem(item[0]))
            self.tableWidget_StackTrace.setItem(row, STACKTRACE_FRAME_ADDRESS_COL, QTableWidgetItem(item[1]))

    def tableWidget_StackTrace_context_menu_event(self, event):
        menu = QMenu()
        switch_to_stack = menu.addAction("Full Stack")
        font_size = self.tableWidget_StackTrace.font().pointSize()
        menu.setStyleSheet("font-size: " + str(font_size) + "pt;")
        action = menu.exec_(event.globalPos())
        if action == switch_to_stack:
            self.stackedWidget_StackScreens.setCurrentWidget(self.Stack)
            self.update_stack()

    def update_stack(self):
        stack_info = GDB_Engine.get_stack_info()
        self.tableWidget_Stack.setRowCount(0)
        self.tableWidget_Stack.setRowCount(len(stack_info))
        for row, item in enumerate(stack_info):
            self.tableWidget_Stack.setItem(row, STACK_POINTER_ADDRESS_COL, QTableWidgetItem(item[0]))
            self.tableWidget_Stack.setItem(row, STACK_VALUE_COL, QTableWidgetItem(item[1]))
            self.tableWidget_Stack.setItem(row, STACK_INT_REPRESENTATION_COL, QTableWidgetItem(item[2]))
            self.tableWidget_Stack.setItem(row, STACK_FLOAT_REPRESENTATION_COL, QTableWidgetItem(item[3]))
        self.tableWidget_Stack.resizeColumnsToContents()

    def tableWidget_Stack_context_menu_event(self, event):
        menu = QMenu()
        switch_to_stacktrace = menu.addAction("Stacktrace")
        font_size = self.tableWidget_Stack.font().pointSize()
        menu.setStyleSheet("font-size: " + str(font_size) + "pt;")
        action = menu.exec_(event.globalPos())
        if action == switch_to_stacktrace:
            self.stackedWidget_StackScreens.setCurrentWidget(self.StackTrace)
            self.update_stacktrace()

    def tableWidget_StackTrace_double_click(self, index):
        if index.column() == STACKTRACE_RETURN_ADDRESS_COL:
            selected_row = self.tableWidget_StackTrace.selectionModel().selectedRows()[-1].row()
            current_address_text = self.tableWidget_StackTrace.item(selected_row, DISAS_ADDR_COL).text()
            current_address = SysUtils.extract_address(current_address_text)
            self.disassemble_expression(current_address, append_to_travel_history=True)

    def widget_Disassemble_wheel_event(self, event):
        steps = event.angleDelta()
        current_address = self.disassemble_currently_displayed_address
        if steps.y() > 0:
            next_address = GDB_Engine.find_address_of_closest_instruction(current_address, instructions_per_scroll,
                                                                          "previous")
        else:
            next_address = GDB_Engine.find_address_of_closest_instruction(current_address, instructions_per_scroll,
                                                                          "next")
        self.disassemble_expression(next_address)

    def widget_HexView_wheel_event(self, event):
        steps = event.angleDelta()
        current_address = self.hex_view_currently_displayed_address
        if steps.y() > 0:
            next_address = current_address - 0x40
        else:
            next_address = current_address + 0x40
        self.hex_dump_address(next_address)

    def tableWidget_Disassemble_key_press_event(self, event):
        selected_row = self.tableWidget_Disassemble.selectionModel().selectedRows()[-1].row()
        current_address_text = self.tableWidget_Disassemble.item(selected_row, DISAS_ADDR_COL).text()
        current_address = SysUtils.extract_address(current_address_text)
        if event.key() == Qt.Key_Space:
            self.follow_instruction(selected_row)
        elif event.key() == Qt.Key_B:
            self.bookmark_address(int(current_address, 16))

    def on_disassemble_double_click(self, index):
        if index.column() == DISAS_COMMENT_COL:
            selected_row = self.tableWidget_Disassemble.selectionModel().selectedRows()[-1].row()
            current_address_text = self.tableWidget_Disassemble.item(selected_row, DISAS_ADDR_COL).text()
            current_address = int(SysUtils.extract_address(current_address_text), 16)
            if current_address in self.tableWidget_Disassemble.bookmarks:
                self.change_bookmark_comment(current_address)
            else:
                self.bookmark_address(current_address)

    # Search the item in given row for location changing instructions
    # Go to the address pointed by that instruction if it contains any
    def follow_instruction(self, selected_row):
        address = SysUtils.extract_address(
            self.tableWidget_Disassemble.item(selected_row, DISAS_OPCODES_COL).text(),
            search_for_location_changing_instructions=True)
        if address:
            self.disassemble_expression(address, append_to_travel_history=True)

    def tableWidget_Disassemble_context_menu_event(self, event):
        selected_row = self.tableWidget_Disassemble.selectionModel().selectedRows()[-1].row()
        current_address_text = self.tableWidget_Disassemble.item(selected_row, DISAS_ADDR_COL).text()
        current_address = SysUtils.extract_address(current_address_text)
        current_address_int = int(current_address, 16)
        first_address = self.disassemble_currently_displayed_address

        menu = QMenu()
        go_to = menu.addAction("Go to expression")
        back = menu.addAction("Back")
        followable = SysUtils.extract_address(
            self.tableWidget_Disassemble.item(selected_row, DISAS_OPCODES_COL).text(),
            search_for_location_changing_instructions=True)
        if followable:
            follow = menu.addAction("Follow[Space]")
        else:
            follow = -1
        is_bookmarked = current_address_int in self.tableWidget_Disassemble.bookmarks
        if not is_bookmarked:
            bookmark = menu.addAction("Bookmark this address[B]")
            delete_bookmark = -1
        else:
            bookmark = -1
            delete_bookmark = menu.addAction("Delete this bookmark")
        go_to_bookmark = menu.addMenu("Go to bookmarked address")
        bookmark_action_list = []
        for item in self.tableWidget_Disassemble.bookmarks.keys():

            # FIXME: Implement and use optimized version of convert_address_to_symbol if performance issues occur
            current_text = GDB_Engine.convert_address_to_symbol(hex(item), include_address=True)
            if current_text is None:
                text_append = hex(item) + "(Unreachable)"
            else:
                text_append = current_text
            bookmark_action_list.append(go_to_bookmark.addAction(text_append))
        menu.addSeparator()
        refresh = menu.addAction("Refresh")
        menu.addSeparator()
        clipboard_menu = menu.addMenu("Copy to Clipboard")
        copy_address = clipboard_menu.addAction("Copy Address")
        copy_bytes = clipboard_menu.addAction("Copy Bytes")
        copy_opcode = clipboard_menu.addAction("Copy Opcode")
        copy_comment = clipboard_menu.addAction("Copy Comment")
        font_size = self.tableWidget_Disassemble.font().pointSize()
        menu.setStyleSheet("font-size: " + str(font_size) + "pt;")
        action = menu.exec_(event.globalPos())
        if action == go_to:
            go_to_dialog = DialogWithButtonsForm(label_text="Enter the expression", hide_line_edit=False,
                                                 line_edit_text=first_address)
            if go_to_dialog.exec_():
                traveled_exp = go_to_dialog.get_values()
                self.disassemble_expression(traveled_exp, append_to_travel_history=True)
        elif action == back:
            if self.tableWidget_Disassemble.travel_history:
                last_location = self.tableWidget_Disassemble.travel_history[-1]
                self.disassemble_expression(last_location)
                self.tableWidget_Disassemble.travel_history.pop()
        elif action == follow:
            self.follow_instruction(selected_row)
        elif action == bookmark:
            self.bookmark_address(current_address_int)
        elif action == delete_bookmark:
            self.delete_bookmark(current_address_int)
        elif action == refresh:
            self.disassemble_expression(self.disassemble_currently_displayed_address)
        elif action == copy_address:
            QApplication.clipboard().setText(self.tableWidget_Disassemble.item(selected_row, DISAS_ADDR_COL).text())
        elif action == copy_bytes:
            QApplication.clipboard().setText(self.tableWidget_Disassemble.item(selected_row, DISAS_BYTES_COL).text())
        elif action == copy_opcode:
            QApplication.clipboard().setText(self.tableWidget_Disassemble.item(selected_row, DISAS_OPCODES_COL).text())
        elif action == copy_comment:
            QApplication.clipboard().setText(self.tableWidget_Disassemble.item(selected_row, DISAS_COMMENT_COL).text())
        for item in bookmark_action_list:
            if action == item:
                self.disassemble_expression(SysUtils.extract_address(action.text()), append_to_travel_history=True)

    def bookmark_address(self, int_address):
        if int_address in self.tableWidget_Disassemble.bookmarks:
            QMessageBox.information(self, "Error", "This address has already been bookmarked")
            return
        comment_dialog = DialogWithButtonsForm(label_text="Enter the comment for bookmarked address",
                                               hide_line_edit=False)
        if comment_dialog.exec_():
            comment = comment_dialog.get_values()
        else:
            return
        self.tableWidget_Disassemble.bookmarks[int_address] = comment
        for row in range(self.tableWidget_Disassemble.rowCount()):
            current_text = self.tableWidget_Disassemble.item(row, DISAS_ADDR_COL).text()
            current_address = int(SysUtils.extract_address(current_text), 16)
            if current_address == int_address:
                self.tableWidget_Disassemble.setItem(row, DISAS_ADDR_COL, QTableWidgetItem("(M)" + current_text))
                self.tableWidget_Disassemble.setItem(row, DISAS_COMMENT_COL, QTableWidgetItem(comment))
                self.set_row_colour(row, BOOKMARK_COLOUR)
                self.tableWidget_Disassemble.resizeColumnsToContents()
                self.tableWidget_Disassemble.horizontalHeader().setStretchLastSection(True)
                break

    def change_bookmark_comment(self, int_address):
        current_comment = self.tableWidget_Disassemble.bookmarks[int_address]
        comment_dialog = DialogWithButtonsForm(label_text="Enter the comment for bookmarked address",
                                               hide_line_edit=False, line_edit_text=current_comment)
        if comment_dialog.exec_():
            new_comment = comment_dialog.get_values()
        else:
            return
        self.tableWidget_Disassemble.bookmarks[int_address] = new_comment
        for row in range(self.tableWidget_Disassemble.rowCount()):
            current_text = self.tableWidget_Disassemble.item(row, DISAS_ADDR_COL).text()
            current_address = int(SysUtils.extract_address(current_text), 16)
            if current_address == int_address:
                self.tableWidget_Disassemble.setItem(row, DISAS_COMMENT_COL, QTableWidgetItem(new_comment))
                self.set_row_colour(row, BOOKMARK_COLOUR)
                self.tableWidget_Disassemble.resizeColumnsToContents()
                self.tableWidget_Disassemble.horizontalHeader().setStretchLastSection(True)
                break

    def delete_bookmark(self, int_address):
        if int_address in self.tableWidget_Disassemble.bookmarks:
            del self.tableWidget_Disassemble.bookmarks[int_address]
            for row in range(self.tableWidget_Disassemble.rowCount()):
                current_text = self.tableWidget_Disassemble.item(row, DISAS_ADDR_COL).text()
                current_address = int(SysUtils.extract_address(current_text), 16)
                if current_address == int_address:
                    mark_removed_text = GuiUtils.remove_bookmark_mark(current_text)
                    self.tableWidget_Disassemble.setItem(row, DISAS_ADDR_COL, QTableWidgetItem(mark_removed_text))
                    self.tableWidget_Disassemble.setItem(row, DISAS_COMMENT_COL, QTableWidgetItem(""))
                    self.set_row_colour(row, DEFAULT_COLOUR)
                    self.tableWidget_Disassemble.resizeColumnsToContents()
                    self.tableWidget_Disassemble.horizontalHeader().setStretchLastSection(True)
                    break

    def on_ViewBookmarks_triggered(self):
        self.bookmark_widget = BookmarkWidgetForm(self)
        self.bookmark_widget.show()

    def on_stacktrace_info_triggered(self):
        self.stacktrace_info_widget = StackTraceInfoWidgetForm()
        self.stacktrace_info_widget.show()

    def on_inject_so_file_triggered(self):
        file_name = QFileDialog.getOpenFileName(self, "Select the .so file", "", "Shared object library (*.so)")[0]
        if file_name:
            if GDB_Engine.inject_with_dlopen_call(file_name):
                QMessageBox.information(self, "Success!", "The file has been injected")
            else:
                QMessageBox.information(self, "Error", "Failed to inject the .so file")

    def on_show_float_registers_button_clicked(self):
        self.float_registers_widget = FloatRegisterWidgetForm()
        self.float_registers_widget.show()
        GuiUtils.center_to_window(self.float_registers_widget, self.widget_Registers)


class BookmarkWidgetForm(QWidget, BookmarkWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setupUi(self)
        GuiUtils.center(self)
        self.setWindowFlags(Qt.Window)
        self.listWidget.contextMenuEvent = self.listWidget_context_menu_event
        self.listWidget.currentRowChanged.connect(self.change_display)
        self.listWidget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.shortcut_delete = QShortcut(QKeySequence("Del"), self)
        self.shortcut_delete.activated.connect(self.delete_record)
        self.refresh_table()

    def refresh_table(self):
        self.listWidget.clear()
        for item in self.parent().tableWidget_Disassemble.bookmarks.keys():

            # FIXME: Implement and use optimized version of convert_address_to_symbol if performance issues occur
            current_text = GDB_Engine.convert_address_to_symbol(hex(item), include_address=True)
            if current_text is None:
                text_append = hex(item) + "(Unreachable)"
            else:
                text_append = current_text
            self.listWidget.addItem(text_append)

    def change_display(self):
        try:
            current_item = self.listWidget.currentItem().text()
        except AttributeError:
            return
        current_address = SysUtils.extract_address(current_item)
        self.lineEdit_Info.setText(GDB_Engine.get_info_about_address(current_address))
        self.lineEdit_Comment.setText(self.parent().tableWidget_Disassemble.bookmarks[int(current_address, 16)])

    def on_item_double_clicked(self, item):
        self.parent().disassemble_expression(SysUtils.extract_address(item.text()), append_to_travel_history=True)

    def listWidget_context_menu_event(self, event):
        if self.listWidget.count() != 0:
            current_item = self.listWidget.currentItem().text()
            current_address = int(SysUtils.extract_address(current_item), 16)
        else:
            current_item = None
            current_address = None
        if current_item is not None:
            if not current_address in self.parent().tableWidget_Disassemble.bookmarks:
                QMessageBox.information(self, "Error", "Invalid entries detected, refreshing the page")
                self.refresh_table()
                return
        menu = QMenu()
        add_entry = menu.addAction("Add new entry")
        if current_item is not None:
            change_comment = menu.addAction("Change comment of this record")
            delete_record = menu.addAction("Delete this record[Del]")
        else:
            change_comment = -1
            delete_record = -1
        menu.addSeparator()
        refresh = menu.addAction("Refresh")
        font_size = self.listWidget.font().pointSize()
        menu.setStyleSheet("font-size: " + str(font_size) + "pt;")
        action = menu.exec_(event.globalPos())
        if action == add_entry:
            entry_dialog = DialogWithButtonsForm(label_text="Enter the expression", hide_line_edit=False)
            if entry_dialog.exec_():
                text = entry_dialog.get_values()
                address = GDB_Engine.convert_symbol_to_address(text)
                if address is None:
                    QMessageBox.information(self, "Error", "Invalid expression or address")
                    return
                self.parent().bookmark_address(int(address, 16))
                self.refresh_table()
        elif action == change_comment:
            self.parent().change_bookmark_comment(current_address)
            self.refresh_table()
        elif action == delete_record:
            self.delete_record()
        elif action == refresh:
            self.refresh_table()

    def delete_record(self):
        current_item = self.listWidget.currentItem().text()
        current_address = int(SysUtils.extract_address(current_item), 16)
        self.parent().delete_bookmark(current_address)
        self.refresh_table()


class FloatRegisterWidgetForm(QTabWidget, FloatRegisterWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setupUi(self)
        self.setWindowFlags(Qt.Window)
        self.update_registers()
        self.tableWidget_FPU.itemDoubleClicked.connect(self.set_register)
        self.tableWidget_XMM.itemDoubleClicked.connect(self.set_register)

    def update_registers(self):
        self.tableWidget_FPU.setRowCount(0)
        self.tableWidget_FPU.setRowCount(8)
        self.tableWidget_XMM.setRowCount(0)
        self.tableWidget_XMM.setRowCount(8)
        float_registers = GDB_Engine.read_float_registers()

        # st0-7, xmm0-7
        for row, index in enumerate(range(8)):
            current_st_register = "st" + str(index)
            current_xmm_register = "xmm" + str(index)
            self.tableWidget_FPU.setItem(row, FLOAT_REGISTERS_NAME_COL, QTableWidgetItem(current_st_register))
            self.tableWidget_FPU.setItem(row, FLOAT_REGISTERS_VALUE_COL,
                                         QTableWidgetItem(float_registers[current_st_register]))
            self.tableWidget_XMM.setItem(row, FLOAT_REGISTERS_NAME_COL, QTableWidgetItem(current_xmm_register))
            self.tableWidget_XMM.setItem(row, FLOAT_REGISTERS_VALUE_COL,
                                         QTableWidgetItem(float_registers[current_xmm_register]))

    def set_register(self, index):
        current_row = index.row()
        if self.currentWidget() == self.FPU:
            current_table_widget = self.tableWidget_FPU
        elif self.currentWidget() == self.XMM:
            current_table_widget = self.tableWidget_XMM
        current_register = current_table_widget.item(current_row, FLOAT_REGISTERS_NAME_COL).text()
        current_value = current_table_widget.item(current_row, FLOAT_REGISTERS_VALUE_COL).text()
        label_text = "Enter the new value of register " + current_register.upper()
        register_dialog = DialogWithButtonsForm(label_text=label_text, hide_line_edit=False,
                                                line_edit_text=current_value)
        if register_dialog.exec_():
            if self.currentWidget() == self.XMM:
                current_register = current_register + ".v4_float"
            GDB_Engine.set_convenience_variable(current_register, register_dialog.get_values())
            self.update_registers()


class StackTraceInfoWidgetForm(QWidget, StackTraceInfoWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setupUi(self)
        GuiUtils.center(self)
        self.setWindowFlags(Qt.Window)
        self.listWidget_ReturnAddresses.currentRowChanged.connect(self.update_frame_info)
        self.update_stacktrace()

    def update_stacktrace(self):
        self.listWidget_ReturnAddresses.clear()
        return_addresses = GDB_Engine.get_stack_frame_return_addresses()
        self.listWidget_ReturnAddresses.addItems(return_addresses)

    def update_frame_info(self, index):
        frame_info = GDB_Engine.get_stack_frame_info(index)
        self.textBrowser_Info.setText(frame_info)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainForm()
    window.show()
    sys.exit(app.exec_())
