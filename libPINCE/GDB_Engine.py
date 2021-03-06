# -*- coding: utf-8 -*-
"""
Copyright (C) 2016 Korcan Karaokçu <korcankaraokcu@gmail.com>

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
from re import search, split, findall, escape
from threading import Lock, Thread, Condition
from time import sleep, time
import pexpect
import os
import ctypes
import pickle
from . import SysUtils
from . import type_defs

INDEX_BYTE = type_defs.VALUE_INDEX.INDEX_BYTE
INDEX_2BYTES = type_defs.VALUE_INDEX.INDEX_2BYTES
INDEX_4BYTES = type_defs.VALUE_INDEX.INDEX_4BYTES
INDEX_8BYTES = type_defs.VALUE_INDEX.INDEX_8BYTES
INDEX_FLOAT = type_defs.VALUE_INDEX.INDEX_FLOAT
INDEX_DOUBLE = type_defs.VALUE_INDEX.INDEX_DOUBLE
INDEX_STRING = type_defs.VALUE_INDEX.INDEX_STRING
INDEX_AOB = type_defs.VALUE_INDEX.INDEX_AOB

INITIAL_INJECTION_PATH = type_defs.PATHS.INITIAL_INJECTION_PATH

INFERIOR_RUNNING = type_defs.INFERIOR_STATUS.INFERIOR_RUNNING
INFERIOR_STOPPED = type_defs.INFERIOR_STATUS.INFERIOR_STOPPED

SIMPLE_DLOPEN_CALL = type_defs.INJECTION_METHOD.SIMPLE_DLOPEN_CALL
ADVANCED_INJECTION = type_defs.INJECTION_METHOD.ADVANCED_INJECTION

ARCH_32 = type_defs.INFERIOR_ARCH.ARCH_32
ARCH_64 = type_defs.INFERIOR_ARCH.ARCH_64

libc = ctypes.CDLL('libc.so.6')
inferior_arch = int

currentpid = 0
child = object  # this object will be used with pexpect operations
lock_send_command = Lock()
gdb_async_condition = Condition()
status_changed_condition = Condition()
inferior_status = -1
gdb_output = ""
gdb_async_output = ""

index_to_gdbcommand_dict = type_defs.index_to_gdbcommand_dict


# The comments next to the regular expressions shows the expected gdb output, hope it helps to the future developers

def send_command(command, control=False, cli_output=False, send_with_file=False, file_contents_send=None,
                 recv_with_file=False):
    """Issues the command sent

    Args:
        command (str): The command that'll be sent
        control (bool): This param should be True if the command sent is ctrl+key instead of the regular command
        cli_output (bool): If True, returns the readable parsed cli output instead of gdb/mi garbage
        send_with_file (bool): Custom commands declared in GDBCommandExtensions.py requires file communication. If
        called command has any parameters, pass this as True
        file_contents_send (any type that pickle.dump supports): Arguments for the called custom gdb command
        recv_with_file (bool): Pass this as True if the called custom gdb command returns something

    Examples:
        send_command(c,control=True)--> Sends ctrl+c instead of the str "c"
        send_command("pince-read-multiple-addresses", file_contents_send=nested_list, recv_file=True)--> This line calls
        the custom gdb command "pince-read-multiple-addresses" with parameter nested_list and since that gdb command
        returns the addresses read as a list, we also pass the parameter recv_file as True

    Returns:
        str: Result of the command sent, commands in the form of "ctrl+key" always returns a null string
        None: If the inferior is running or no inferior has been selected

    Todo:
        Support GDB/MI commands. In fact, this is something gdb itself should fix. Because gdb python API doesn't
        support gdb/mi commands and since PINCE uses gdb python API, it can't support gdb/mi commands as well

    Note:
        File communication system is used to avoid BEL emitting bug of pexpect. If you send more than a certain amount
        of characters to gdb, the input will be sheared at somewhere and gdb won't be receiving all of the input
        Visit this page for more information-->http://pexpect.readthedocs.io/en/stable/commonissues.html
    """
    global child
    global gdb_output
    with lock_send_command:
        time0 = time()
        if currentpid == 0:
            print("no process has been selected")
            return
        if inferior_status is INFERIOR_RUNNING and not control:
            print("inferior is running")
            return
        gdb_output = ""
        if send_with_file:
            send_file = SysUtils.get_ipc_from_PINCE_file(currentpid)
            pickle.dump(file_contents_send, open(send_file, "wb"))
        if recv_with_file or cli_output:
            recv_file = SysUtils.get_ipc_to_PINCE_file(currentpid)

            # Truncating the recv_file because we wouldn't like to see output of previous command in case of errors
            open(recv_file, "w").close()
        command = str(command)
        print("Last command: " + (command if not control else "Ctrl+" + command))
        if control:
            child.sendcontrol(command)
        else:
            command_file = SysUtils.get_gdb_command_file(currentpid)
            command_fd = open(command_file, "w")
            command_fd.write(command)
            command_fd.close()
            if not cli_output:
                child.sendline("source " + command_file)
            else:
                child.sendline("cli-output source " + command_file)
        if not control:
            while gdb_output is "":
                sleep(0.00001)
        if not control:
            if recv_with_file or cli_output:
                output = pickle.load(open(recv_file, "rb"))
            else:
                output = gdb_output
        else:
            output = ""
        if type(output) == str:
            output = output.strip()
        time1 = time()
        print(time1 - time0)
        return output


def can_attach(pid):
    """Check if we can attach to the target

    Args:
        pid (int,str): PID of the process that'll be attached

    Returns:
        bool: True if attaching is successful, False otherwise
    """
    result = libc.ptrace(16, int(pid), 0, 0)  # 16 is PTRACE_ATTACH, check ptrace.h for details
    if result is -1:
        return False
    os.waitpid(int(pid), 0)
    libc.ptrace(17, int(pid), 0, 17)  # 17 is PTRACE_DETACH, check ptrace.h for details
    sleep(0.01)
    return True


def state_observe_thread():
    """
    Observes the state of gdb, uses conditions to inform other functions and threads about gdb's state
    Also generates output for send_command function
    Should be called by creating a thread. Usually called in initialization process by attach function
    """
    global inferior_status
    global child
    global gdb_output
    global gdb_async_output
    while True:
        child.expect_exact("(gdb)")
        print(child.before)  # debug mode on!
        matches = findall(r"stopped\-threads=\"all\"|\*running,thread\-id=\"all\"",
                          child.before)  # stopped-threads="all"  # *running,thread-id="all"
        if len(matches) > 0:
            if search(r"stopped", matches[-1]):
                inferior_status = INFERIOR_STOPPED
            else:
                inferior_status = INFERIOR_RUNNING
            with status_changed_condition:
                status_changed_condition.notify_all()
        try:
            # The command will always start with the word "source", check send_command function for the cause
            command_file = escape(SysUtils.get_gdb_command_file(currentpid))
            gdb_output = split(r"&\".*source\s" + command_file + r"\\n\"", child.before, 1)[1]  # &"command\n"
        except:
            with gdb_async_condition:
                gdb_async_output = child.before
                gdb_async_condition.notify_all()


def interrupt_inferior():
    """Interrupt the inferior"""
    send_command("c", control=True)


def continue_inferior():
    """Continue the inferior"""
    send_command("c")


def attach(pid):
    """Attaches gdb to the target and initializes some of the global variables

    Args:
        pid (int,str): PID of the process that'll be attached to
    """
    global currentpid
    global child
    global inferior_arch
    currentpid = int(pid)
    SysUtils.create_PINCE_IPC_PATH(pid)
    currentdir = SysUtils.get_current_script_directory()
    child = pexpect.spawn('sudo LC_NUMERIC=C gdb --interpreter=mi', cwd=currentdir, encoding="utf-8")
    child.setecho(False)
    child.delaybeforesend = 0
    child.timeout = None
    child.expect_exact("(gdb)")
    status_thread = Thread(target=state_observe_thread)
    status_thread.daemon = True
    status_thread.start()
    send_command("set logging file " + SysUtils.get_gdb_async_file(pid))
    send_command("set logging on")
    send_command("attach " + str(pid))

    # gdb scripts needs to know PINCE directory, unfortunately they don't start from the place where script exists
    send_command('set $PINCE_PATH=' + '"' + currentdir + '"')
    send_command("source libPINCE/gdb_python_scripts/GDBCommandExtensions.py")
    inferior_arch = get_inferior_arch()
    continue_inferior()


def detach():
    """See you, space cowboy"""
    global child
    global currentpid
    global inferior_status
    child.sendcontrol("d")
    child.close()
    currentpid = 0
    inferior_status = -1


def inject_with_advanced_injection(library_path):
    """Injects the given .so file to current process

    Args:
        library_path (str): Path to the .so file that'll be injected

    Returns:
        bool: Result of the injection

    Notes:
        This function was reserved for linux-inject and since linux-inject is no more(F to pay respects), I'll leave
        this function as a template for now
    """
    raise NotImplementedError


def inject_with_dlopen_call(library_path):
    """Injects the given .so file to current process
    This is a variant of the function inject_with_advanced_injection
    This function won't break the target process unlike other complex injection methods
    The downside is it fails if the target doesn't support dlopen calls or simply doesn't have the library

    Args:
        library_path (str): Path to the .so file that'll be injected

    Returns:
        bool: Result of the injection
    """
    injectionpath = '"' + library_path + '"'
    result = send_command("call dlopen(" + injectionpath + ", 1)")
    filtered_result = search(r"\$\d+\s*=\s*\-*\d+", result)  # $1 = -1633996800
    if filtered_result:
        dlopen_return_value = split(" ", filtered_result.group(0))[-1]
        if dlopen_return_value is "0":
            result = send_command("call __libc_dlopen_mode(" + injectionpath + ", 1)")
            filtered_result = search(r"\$\d+\s*=\s*\-*\d+", result)  # $1 = -1633996800
            if filtered_result:
                dlopen_return_value = split(" ", filtered_result.group(0))[-1]
                if dlopen_return_value is "0":
                    return False
                return True
            return False
        return True
    result = send_command("call __libc_dlopen_mode(" + injectionpath + ", 1)")
    filtered_result = search(r"\$\d+\s*=\s*\-*\d+", result)  # $1 = -1633996800
    if filtered_result:
        dlopen_return_value = split(" ", filtered_result.group(0))[-1]
        if dlopen_return_value is "0":
            return False
        return True
    return False


def value_index_to_gdbcommand(index=int):
    """Converts the given value_index to a parameter that'll be used in "x" command of gdb

    Args:
        index (int): Can be a member of type_defs.VALUE_INDEX

    Returns:
        str: The str corresponding to the index in type_defs.index_to_gdbcommand_dict
    """
    return index_to_gdbcommand_dict.get(index, "out of bounds")


def check_for_restricted_gdb_symbols(string):
    """Checks for characters that cause unexpected behaviour
    "$" makes gdb show it's value history(e.g $4=4th value) and it's convenience variables(such as $pc, $g_thread)
    Also whitespaces(or simply inputting nothing) makes gdb show the last shown value
    If you don't like the user to see these, use this function to check the input

    Args:
        string (str): The str that'll be checked for specific characters

    Returns:
        bool: True if one of the characters are encountered, False otherwise
    """
    string = str(string)
    string = string.strip()
    if string is "":
        return True
    if search(r"\".*\"", string) or search(r"\{.*\}", string):  # For string and array expressions
        return False
    if search(r'\$', string):  # These characters make gdb show it's value history, so they should be avoided
        return True
    return False


def read_single_address_by_expression(expression, value_index, length=None, is_unicode=False, zero_terminate=True,
                                      check=True):
    """Reads value from the given address or expression by using "x" command of gdb then converts it to the given
    value type

    The expression can also be a function name such as "_start", "malloc", "printf" and "scanf"

    Args:
        expression (str): Can be a hex string or an expression. By default, expressions using the character "$" are not
        permitted. The character "$" is useful when displaying convenience variables, but it's also confusing because it
        makes gdb show it's value history. To include "$" in the permitted characters, pass the parameter check as True
        value_index (int): Determines the type of data read. Can be a member of type_defs.VALUE_INDEX
        length (int): Length of the data that'll be read. Only used when the value_index is INDEX_STRING or INDEX_AOB.
        Ignored otherwise.
        is_unicode (bool): If True, data will be considered as utf-8, ascii otherwise. Only used when value_index is
        INDEX_STRING. Ignored otherwise.
        zero_terminate (bool): If True, data will be split when a null character has been read. Only used when
        value_index is INDEX_STRING. Ignored otherwise.
        check (bool): If True, the parameter expression will be checked by check_for_restricted_gdb_symbols function. If
        any specific character is found, this function will return "??"

    Returns:
        str: The value of address read as str. If the expression/address is not valid, returns the string "??"
    """
    if check:
        if check_for_restricted_gdb_symbols(expression):
            return "??"
    if length is "":
        return "??"
    if value_index is INDEX_AOB:
        typeofaddress = value_index_to_gdbcommand(value_index)
        try:
            expectedlength = str(int(length))  # length must be a legit number, so had to do this trick
        except:
            return "??"
        result = send_command("x/" + expectedlength + typeofaddress + " " + expression)
        filteredresult = findall(r"\\t0x[0-9a-fA-F]+", result)  # 0x40c431:\t0x31\t0xed\t0x49\t...
        if filteredresult:
            returned_string = ''.join(filteredresult)  # combine all the matched results
            return returned_string.replace(r"\t0x", " ")
        return "??"
    elif value_index is INDEX_STRING:
        typeofaddress = value_index_to_gdbcommand(value_index)
        if not is_unicode:
            try:
                expectedlength = str(int(length))
            except:
                return "??"
            result = send_command("x/" + expectedlength + typeofaddress + " " + expression)
        else:
            try:
                expectedlength = str(int(length) * 2)
            except:
                return "??"
            result = send_command("x/" + expectedlength + typeofaddress + " " + expression)
        filteredresult = findall(r"\\t0x[0-9a-fA-F]+", result)  # 0x40c431:\t0x31\t0xed\t0x49\t...
        if filteredresult:
            filteredresult = ''.join(filteredresult)
            returned_string = filteredresult.replace(r"\t0x", "")
            if not is_unicode:
                returned_string = bytes.fromhex(returned_string).decode("ascii", "replace")
            else:
                returned_string = bytes.fromhex(returned_string).decode("utf-8", "replace")
            if zero_terminate:
                if returned_string.startswith('\x00'):
                    returned_string = '\x00'
                else:
                    returned_string = returned_string.split('\x00')[0]
            return returned_string[0:int(length)]
        return "??"
    else:
        typeofaddress = value_index_to_gdbcommand(value_index)
        result = send_command("x/" + typeofaddress + " " + expression)
        filteredresult = search(r":\\t[0-9a-fA-F-,]+", result)  # 0x400000:\t1,3961517377359369e-309
        if filteredresult:
            return split("t", filteredresult.group(0))[-1]
        return "??"


def read_single_address(address, value_index, length=None, is_unicode=False, zero_terminate=True):
    """Reads value from the given address by using an optimized gdb python script

    A variant of the function read_single_address_by_expression. This function is slightly faster and it only accepts
    addresses instead of expressions. Use this function if you like to read only addresses, use the other variant if you
    also would like to input expressions. This function also calculates float and double variables more precisely, for
    instance, if you calculate the address 0x40c495(_start+100) on KMines with value_index=INDEX_DOUBLE with the
    function read_single_address_by_expression(which uses gdb's "x" command), you'll get the result "6". But if you use
    this function instead(custom script), you'll get the result "6.968143721100816e+38" instead

    Args:
        address (str): Can be a hex string.
        value_index (int): Determines the type of data read. Can be a member of type_defs.VALUE_INDEX
        length (int): Length of the data that'll be read. Only used when the value_index is INDEX_STRING or INDEX_AOB.
        Ignored otherwise.
        is_unicode (bool): If True, data will be considered as utf-8, ascii otherwise. Only used when value_index is
        INDEX_STRING. Ignored otherwise.
        zero_terminate (bool): If True, data will be split when a null character has been read. Only used when
        value_index is INDEX_STRING. Ignored otherwise.

    Returns:
        str: If the value_index is INDEX_STRING or INDEX_AOB. If an error occurs when reading, returns a null string
        float: If the value_index is INDEX_FLOAT or INDEX_DOUBLE
        int: If the value_index is anything else
    """
    return send_command("pince-read-single-address", send_with_file=True,
                        file_contents_send=(address, value_index, length, is_unicode, zero_terminate),
                        recv_with_file=True)


def read_multiple_addresses(nested_list):
    """Reads multiple values from the given addresses by using an optimized gdb python script

    Optimized version of the function read_single_address. This function is significantly faster after 100 addresses
    compared to using read_single_address in a for loop.

    Args:
        nested_list (list): List of *args of the function read_single_address. You don't have to pass all of the
        parameters for each list in the nested_list, only parameters address and value_index are obligatory. Defaults
        of the other parameters are the same with the function read_single_address.

    Examples:
        All parameters are passed-->[[address1, value_index1, length1, unicode1, zero_terminate1],[address2, ...], ...]
        Parameters are partially passed--▼
        [[address1, value_index1],[address2, value_index2, length2],[address3, value_index3, zero_terminate], ...]

    Returns:
        list: A list of the values read.
        If any errors occurs while reading addresses, it's ignored and the belonging address is returned as null string
        For instance; If 4 addresses has been read and 3rd one is problematic, the returned list will be
        [returned_value1,returned_value2,"",returned_value4]
    """
    contents_recv = send_command("pince-read-multiple-addresses", send_with_file=True, file_contents_send=nested_list,
                                 recv_with_file=True)
    if contents_recv is None:
        print("an error occurred while reading addresses")
        contents_recv = []
    return contents_recv


def set_multiple_addresses(nested_list, value):
    """Sets the given value to the given addresses by using an optimized gdb python script

    There's no single version of this function yet. Use this even for single addresses
    If any errors occurs while setting values to the according addresses, it'll be ignored but the information about
    error will be printed to the terminal.

    Args:
        nested_list (list): List of the address and value_index parameters of the function read_single_address
        Both parameters address and value_index are necessary.
        value (str): The value that'll be written to the given addresses

    Examples:
        nested_list-->[[address1, value_index1],[address2, value_index2], ...]
    """
    nested_list.append(value)
    send_command("pince-set-multiple-addresses", send_with_file=True, file_contents_send=nested_list)


def disassemble(expression, offset_or_address):
    """Disassembles the address evaluated by the given expression

    Args:
        expression (str): Any gdb expression
        offset_or_address (str): If you pass this parameter as an offset, you should add "+" in front of it
        (e.g "+42" or "+0x42"). If you pass this parameter as an hex address, the address range between the expression
        and the secondary address is disassembled.
        If the second parameter is an address. it always should be bigger than the first address.

    Returns:
        list: A list of str values in this format-->[[address1,bytes1,opcodes1],[address2, ...], ...]
    """
    returned_list = []
    output = send_command("disas /r " + expression + "," + offset_or_address)
    filtered_output = findall(r"0x[0-9a-fA-F]+.*\\t.+\\t.+\\n",
                              output)  # 0x00007fd81d4c7400 <__printf+0>:\t48 81 ec d8 00 00 00\tsub    rsp,0xd8\n
    for item in filtered_output:
        returned_list.append(list(filter(None, split(r"\\t|\\n", item))))
    return returned_list


def convert_address_to_symbol(expression, include_address=False, check=True):
    """Converts the address evaluated by the given expression to symbol if any symbol exists for it

    Args:
        expression (str): Any gdb expression
        include_address (bool): If true, returned string includes address
        check (bool): If your string contains one of the restricted characters($ etc.) pass the check parameter as False

    Returns:
        str: Symbol of corresponding address(such as printf, scanf, _start etc.). If no symbols are found, address as
        str returned instead. If include_address is passed as True, returned str looks like this-->0x40c435 <_start+4>
        If the parameter "check" is True, returns the expression itself untouched if any restricted characters are found
        None: If the address is unreachable
    """
    if check:
        if check_for_restricted_gdb_symbols(expression):
            return expression
    result = send_command("x/b " + expression)
    if search(r"Cannot\s*access\s*memory\s*at\s*address", result):
        return
    filteredresult = search(r"0x[0-9a-fA-F]+\s+<.+>:\\t", result)  # 0x40c435 <_start+4>:\t0x89485ed1\n
    if filteredresult:
        if include_address:
            return split(":", filteredresult.group(0))[0]
        return split(">:", filteredresult.group(0))[0].split("<")[1]
    else:
        filteredresult = search(r"0x[0-9a-fA-F]+:\\t", result)  # 0x1f58010:\t0x00647361\n
        if filteredresult:
            return split(":", filteredresult.group(0))[0]


def convert_symbol_to_address(expression, check=True):
    """Converts the symbol evaluated by the given expression to address

    Args:
        expression (str): Any gdb expression
        check (bool): If your string contains one of the restricted symbols(such as $) pass the check parameter as False

    Returns:
        str: Address of corresponding symbol
        If the parameter "check" is True, returns the expression itself untouched if any restricted characters are found
        None: If the address is unreachable
    """
    if check:
        if check_for_restricted_gdb_symbols(expression):
            return expression
    result = send_command("x/b " + expression)
    if search(r"Cannot\s*access\s*memory\s*at\s*address", result):
        return
    filteredresult = search(r"0x[0-9a-fA-F]+\s+<.+>:\\t", result)  # 0x40c435 <_start+4>:\t0x89485ed1\n
    if filteredresult:
        return split(" ", filteredresult.group(0))[0]
    else:
        filteredresult = search(r"0x[0-9a-fA-F]+:\\t", result)  # 0x1f58010:\t0x00647361\n
        if filteredresult:
            return split(":", filteredresult.group(0))[0]


def parse_convenience_variables(variables):
    """Converts the convenience variables to their str equivalents

    Args:
        variables (str): The convenience variables, splitted by a ",".

    Examples:
        variables-->"$pc,$_gthread,$_inferior,$_exitcode,$_siginfo"

    Returns:
        list: List of str values of the corresponding convenience variables
    """
    variables = variables.replace(" ", "")
    variable_list = variables.split(",")
    contents_recv = send_command("pince-parse-convenience-variables", send_with_file=True,
                                 file_contents_send=variable_list,
                                 recv_with_file=True)
    if contents_recv is None:
        print("an error occurred while reading variables")
        contents_recv = []
    return contents_recv


# Returns address and the LWP of the current thread
def get_current_thread_information():
    """Gather information about the current thread

    Returns:
        str: "Thread "+thread_address+" (LWP "+LWP_ID+")"

    Examples:
        returned_str-->"Thread 0x7f34730d77c0 (LWP 6189)"
    """
    thread_info = send_command("info threads")
    parsed_info = search(r"\*\s+\d+\s+Thread\s+0x[0-9a-fA-F]+\s+\(LWP\s+\d+\)",
                         thread_info).group(0)  # * 1    Thread 0x7f34730d77c0 (LWP 6189)
    return split(r"Thread\s+", parsed_info)[-1]


def find_address_of_closest_instruction(address, how_many_instructions_to_look_for=1, instruction_location="next"):
    """Finds address of the closest instruction next to the given address, assuming that the given address is valid

    Args:
        address (str): Hex address
        how_many_instructions_to_look_for (int): Number of the instructions that'll be lo- OH COME ON NOW! That one is
        obvious!
        instruction_location (str): If it's "next", instructions coming after the address is searched. If it's anything
        else, the instructions coming before the address is searched instead.

    Returns:
        str: The address found as hex string. If starting/ending of a valid memory range is reached, starting/ending
        address is returned instead as hex string.
    """
    if instruction_location == "next":
        offset = "+" + str(how_many_instructions_to_look_for * 30)
        disas_data = disassemble(address, address + offset)
    else:
        offset = "-" + str(how_many_instructions_to_look_for * 30)
        disas_data = disassemble(address + offset, address)
    if not disas_data:
        if instruction_location != "next":
            start_address = SysUtils.get_region_info(currentpid, address).start
            disas_data = disassemble(start_address, address)
    if instruction_location == "next":
        try:
            return SysUtils.extract_address(disas_data[how_many_instructions_to_look_for][0])
        except IndexError:
            return SysUtils.get_region_info(currentpid, address).end
    else:
        try:
            return SysUtils.extract_address(disas_data[-how_many_instructions_to_look_for][0])
        except IndexError:
            try:
                return start_address
            except UnboundLocalError:
                return SysUtils.get_region_info(currentpid, address).start


def get_info_about_address(expression):
    """Runs the gdb command "info symbol" for given expression and returns the result of it

    Args:
        expression (str): Any gdb expression

    Returns:
        str: The result of the command "info symbol" for given expression
    """
    return send_command("info symbol " + expression, cli_output=True)


def get_inferior_arch():
    """Returns the architecture of the current inferior

    Returns:
        int: A member of type_defs.INFERIOR_ARCH
    """
    if parse_convenience_variables("$rax")[0] == "void":
        return ARCH_32
    return ARCH_64


def read_registers():
    """Returns the current registers

    Returns:
        dict: A dict that holds general registers, flags and segment registers
    """
    contents_recv = send_command("pince-read-registers", recv_with_file=True)
    if contents_recv is None:
        print("an error occurred while reading registers")
        contents_recv = {}
    return contents_recv


def read_float_registers():
    """Returns the current floating point registers

    Returns:
        dict: A dict that holds float registers(st0-7, xmm0-7)
    """
    contents_recv = send_command("pince-read-float-registers", recv_with_file=True)
    if contents_recv is None:
        print("an error occurred while reading float registers")
        contents_recv = {}
    return contents_recv


def set_convenience_variable(variable, value):
    """Sets given convenience variable to given value

    Args:
        variable (str): Any gdb convenience variable(with "$" character removed)
        value (str): Anything
    """
    send_command("set $" + variable + "=" + value)


def set_register_flag(flag, value):
    """Sets given register flag to given value

    Args:
        flag (str): "cf", "pf", "af", "zf", "sf", "tf", "if", "df" or "of"
        value (str): "0" or "1"
        Theoretically, you can pass anything as value. But, it may fuck other flag registers... VERY BADLY!
    """
    registers = read_registers()
    registers[flag] = value
    eflags_hex_value = hex(int(
        registers["of"] + registers["df"] + registers["if"] + registers["tf"] + registers["sf"] + registers[
            "zf"] + "0" + registers["af"] + "0" + registers["pf"] + "0" + registers["cf"], 2))
    set_convenience_variable("eflags", eflags_hex_value)


def get_stacktrace_info():
    """Returns information about current stacktrace

    Returns:
        list: A list of str values in this format-->[[return_address_info1,frame_address_info1],[info2, ...], ...]

        return_address_info looks like this-->Return address of frame+symbol-->0x40c431 <_start>
        frame_address_info looks like this-->Beginning of frame+distance from stack pointer-->0x7ffe1e989a40(rsp+0x100)
    """
    contents_recv = send_command("pince-get-stack-trace-info", recv_with_file=True)
    if contents_recv is None:
        print("an error occurred while reading stacktrace")
        contents_recv = []
    return contents_recv


def get_stack_info():
    """Returns information about current stack

    Returns:
        list: A list of str values in this format--▼
        [[stack_pointer_info1,hex_value1,int_representation1,float_representation1],[stack_pointer_info2, ...], ...]

        stack_pointer_info looks like this-->Hex address+distance from stack pointer-->0x7ffd0d232f88(rsp+0xff8)
        hex_value looks like this-->Value holden by corresponding address-->0x00302e322d63726b
        int_representation looks like this-->integer representation of the hex_value-->13561591926846059
        float_representation looks like this-->float representation of the hex_value--->9.000675827832922e-308
    """
    contents_recv = send_command("pince-get-stack-info", recv_with_file=True)
    if contents_recv is None:
        print("an error occurred while reading stack")
        contents_recv = []
    return contents_recv


def get_stack_frame_return_addresses():
    """Returns return addresses of stack frames

    Returns:
        list: A list of str values in this format-->[return_address_info1,return_address_info2, ...]

        return_address_info looks like this-->Return address of frame+symbol-->0x40c431 <_start>
    """
    contents_recv = send_command("pince-get-frame-return-addresses", recv_with_file=True)
    if contents_recv is None:
        print("an error occurred while reading return addresses of stack frames")
        contents_recv = []
    return contents_recv


def get_stack_frame_info(index):
    """Returns information about stack by the given index

    Args:
        index (int,str): Index of the frame

    Returns:
        str: Information that looks like this--▼
        Stack level 0, frame at 0x7ffc5f87f6a0:
            rip = 0x7fd1d639412d in poll (../sysdeps/unix/syscall-template.S:81); saved rip = 0x7fd1d27fcfe4
            called by frame at 0x7ffc5f87f700
            source language asm.
            Arglist at 0x7ffc5f87f688, args:
            Locals at 0x7ffc5f87f688, Previous frame's sp is 0x7ffc5f87f6a0
            Saved registers:
                rip at 0x7ffc5f87f698
    """
    contents_recv = send_command("pince-get-frame-info", send_with_file=True, file_contents_send=str(index),
                                 recv_with_file=True)
    if contents_recv is None:
        print("an error occurred while reading stack frame " + str(index))
    return contents_recv


def hex_dump(address, offset):
    """Returns hex dump of range (address to address+offset)

    Args:
        address (int,str): Hex address or an int
        offset (int,str): The range that'll be read

    Returns:
        list: List of strings read as str. If an error occurs while reading a memory cell, that cell is returned as "??"

    Examples:
        returned list-->["??","??","??","7f","43","67","40","??","??, ...]
    """
    if type(address) != int:
        address = int(address, 16)
    if type(offset) != int:
        offset = int(offset)
    contents_recv = send_command("pince-hex-dump", send_with_file=True, file_contents_send=(address, offset),
                                 recv_with_file=True)
    if contents_recv is None:
        print("an error occurred while hex dumping address " + hex(address) + " with offset " + str(offset))
    return contents_recv
