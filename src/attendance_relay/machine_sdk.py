from __future__ import annotations

import ctypes
import os
from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ENROLL_DATA_SIZE_FP = (1404 + 12) // 4
ENROLL_DATA_SIZE_FACE = 27668 // 4
BACKUP_NUMBER_CARD = 11
BACKUP_NUMBER_FACE = 17


@dataclass(slots=True)
class EnrollData1Result:
    privilege: int
    password_or_card: int
    backup_number: int
    template_base64: str | None


@dataclass(slots=True)
class DeviceModelInfo:
    is_big_user_id: bool
    company_type: int
    machine_type: int
    machine_version: int


class MachineSdkError(RuntimeError):
    pass


class SBXPCClient:
    def __init__(self, dll_path: str | Path) -> None:
        if os.name != "nt":
            raise MachineSdkError("SBXPC SDK sync is supported only on Windows.")

        self.dll_path = Path(dll_path)
        if not self.dll_path.exists():
            raise MachineSdkError(f"SDK DLL not found: {self.dll_path}")

        self._bstr_t = ctypes.c_void_p
        self._long_t = ctypes.c_long
        self._bool_t = ctypes.c_int

        self._dll = ctypes.WinDLL(str(self.dll_path))
        self._ole = ctypes.windll.oleaut32
        self._configure_ole()
        self._configure_dll()

    def _configure_ole(self) -> None:
        self._ole.SysAllocString.argtypes = [ctypes.c_wchar_p]
        self._ole.SysAllocString.restype = self._bstr_t
        self._ole.SysFreeString.argtypes = [self._bstr_t]
        self._ole.SysFreeString.restype = None

    def _configure_dll(self) -> None:
        self._dll._DotNET.argtypes = []
        self._dll._DotNET.restype = None

        self._dll._ConnectTcpip.argtypes = [
            self._long_t,
            ctypes.POINTER(self._bstr_t),
            self._long_t,
            self._long_t,
        ]
        self._dll._ConnectTcpip.restype = self._bool_t

        self._dll._Disconnect.argtypes = [self._long_t]
        self._dll._Disconnect.restype = None

        self._dll._EnableDevice.argtypes = [self._long_t, self._bool_t]
        self._dll._EnableDevice.restype = self._bool_t

        self._dll._EnableUser.argtypes = [
            self._long_t,
            self._long_t,
            self._long_t,
            self._long_t,
            self._bool_t,
        ]
        self._dll._EnableUser.restype = self._bool_t

        self._dll._SetUserName1.argtypes = [
            self._long_t,
            self._long_t,
            ctypes.POINTER(self._bstr_t),
        ]
        self._dll._SetUserName1.restype = self._bool_t

        self._dll._GetUserName1.argtypes = [
            self._long_t,
            self._long_t,
            ctypes.POINTER(self._bstr_t),
        ]
        self._dll._GetUserName1.restype = self._bool_t

        self._dll._ReadAllUserID.argtypes = [self._long_t]
        self._dll._ReadAllUserID.restype = self._bool_t

        self._dll._GetAllUserID.argtypes = [
            self._long_t,
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
        ]
        self._dll._GetAllUserID.restype = self._bool_t

        self._dll._DeleteEnrollData.argtypes = [
            self._long_t,
            self._long_t,
            self._long_t,
            self._long_t,
        ]
        self._dll._DeleteEnrollData.restype = self._bool_t

        self._dll._GetEnrollData1.argtypes = [
            self._long_t,
            self._long_t,
            self._long_t,
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
        ]
        self._dll._GetEnrollData1.restype = self._bool_t

        self._dll._GetDeviceModel.argtypes = [
            self._long_t,
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
        ]
        self._dll._GetDeviceModel.restype = self._bool_t

        self._dll._SetEnrollData1.argtypes = [
            self._long_t,
            self._long_t,
            self._long_t,
            self._long_t,
            ctypes.POINTER(self._long_t),
            self._long_t,
        ]
        self._dll._SetEnrollData1.restype = self._bool_t

        self._dll._GetDeviceTime.argtypes = [
            self._long_t,
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
            ctypes.POINTER(self._long_t),
        ]
        self._dll._GetDeviceTime.restype = self._bool_t

        self._dll._GeneralOperationXML.argtypes = [self._long_t, ctypes.POINTER(self._bstr_t)]
        self._dll._GeneralOperationXML.restype = self._bool_t

        self._dll._XML_AddString.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
        ]
        self._dll._XML_AddString.restype = self._bool_t

        self._dll._XML_AddInt.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            ctypes.c_int,
        ]
        self._dll._XML_AddInt.restype = self._bool_t

        self._dll._XML_AddLong.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            self._long_t,
        ]
        self._dll._XML_AddLong.restype = self._bool_t

        self._dll._XML_AddBoolean.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            self._bool_t,
        ]
        self._dll._XML_AddBoolean.restype = self._bool_t

        self._dll._XML_AddBinaryByte.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ubyte),
            self._long_t,
        ]
        self._dll._XML_AddBinaryByte.restype = self._bool_t

        self._dll._XML_ParseString.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            ctypes.POINTER(self._bstr_t),
        ]
        self._dll._XML_ParseString.restype = self._bool_t

        self._dll._XML_ParseInt.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
        ]
        self._dll._XML_ParseInt.restype = self._long_t

        self._dll._XML_ParseLong.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
        ]
        self._dll._XML_ParseLong.restype = self._long_t

        self._dll._XML_ParseBoolean.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
        ]
        self._dll._XML_ParseBoolean.restype = self._bool_t

        self._dll._XML_ParseBinaryByte.argtypes = [
            ctypes.POINTER(self._bstr_t),
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_ubyte),
            self._long_t,
        ]
        self._dll._XML_ParseBinaryByte.restype = self._bool_t

        self._dll._GetLastError.argtypes = [self._long_t, ctypes.POINTER(self._long_t)]
        self._dll._GetLastError.restype = self._bool_t

    def dotnet(self) -> None:
        self._dll._DotNET()

    def last_error(self, machine_number: int) -> int | None:
        error_code = self._long_t(0)
        ok = bool(self._dll._GetLastError(machine_number, ctypes.byref(error_code)))
        if not ok:
            return None
        return int(error_code.value)

    def connect_tcpip(self, machine_number: int, ip_address: str, port: int, password: int) -> None:
        ip_ptr = self._alloc_bstr(ip_address)
        try:
            ok = bool(
                self._dll._ConnectTcpip(
                    machine_number,
                    ctypes.byref(ip_ptr),
                    port,
                    password,
                )
            )
        finally:
            self._free_bstr(ip_ptr)

        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "ConnectTcpip failed"))

    def disconnect(self, machine_number: int) -> None:
        self._dll._Disconnect(machine_number)

    def enable_device(self, machine_number: int, enabled: bool) -> None:
        flag = 1 if enabled else 0
        ok = bool(self._dll._EnableDevice(machine_number, flag))
        if not ok:
            state = "enable" if enabled else "disable"
            raise MachineSdkError(self._format_last_error(machine_number, f"EnableDevice({state}) failed"))

    def enable_user(
        self,
        machine_number: int,
        user_id: int,
        *,
        e_machine_number: int = 1,
        backup_number: int = 0,
        enabled: bool = True,
    ) -> None:
        flag = 1 if enabled else 0
        ok = bool(
            self._dll._EnableUser(
                machine_number,
                user_id,
                e_machine_number,
                backup_number,
                flag,
            )
        )
        if not ok:
            state = "enable" if enabled else "disable"
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"EnableUser({state}) failed for user_id={user_id}",
                )
            )

    def get_user_name(self, machine_number: int, user_id: int) -> str:
        name_ptr = self._bstr_t()
        try:
            ok = bool(self._dll._GetUserName1(machine_number, user_id, ctypes.byref(name_ptr)))
            value = self._bstr_to_string(name_ptr)
        finally:
            self._free_bstr(name_ptr)

        if not ok:
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"GetUserName1 failed for user_id={user_id}",
                )
            )
        return value

    def list_all_user_ids(self, machine_number: int) -> list[dict[str, int | bool]]:
        ok = bool(self._dll._ReadAllUserID(machine_number))
        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "ReadAllUserID failed"))

        rows: list[dict[str, int | bool]] = []
        while True:
            user_id = self._long_t(0)
            e_machine_number = self._long_t(0)
            backup_number = self._long_t(0)
            machine_privilege = self._long_t(0)
            enabled = self._long_t(0)

            has_row = bool(
                self._dll._GetAllUserID(
                    machine_number,
                    ctypes.byref(user_id),
                    ctypes.byref(e_machine_number),
                    ctypes.byref(backup_number),
                    ctypes.byref(machine_privilege),
                    ctypes.byref(enabled),
                )
            )
            if not has_row:
                break

            rows.append(
                {
                    "user_id": int(user_id.value),
                    "e_machine_number": int(e_machine_number.value),
                    "backup_number": int(backup_number.value),
                    "machine_privilege": int(machine_privilege.value),
                    "enabled": int(enabled.value) != 0,
                }
            )
        return rows

    def get_enroll_data1(self, machine_number: int, user_id: int, backup_number: int) -> EnrollData1Result:
        privilege = self._long_t(0)
        password = self._long_t(0)
        template = (self._long_t * ENROLL_DATA_SIZE_FACE)()
        ok = bool(
            self._dll._GetEnrollData1(
                machine_number,
                user_id,
                backup_number,
                ctypes.byref(privilege),
                ctypes.cast(template, ctypes.POINTER(self._long_t)),
                ctypes.byref(password),
            )
        )
        if not ok:
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"GetEnrollData1 failed for user_id={user_id} backup={backup_number}",
                )
            )

        active_size = ENROLL_DATA_SIZE_FACE if backup_number == BACKUP_NUMBER_FACE else ENROLL_DATA_SIZE_FP
        raw = b"".join(
            int(template[index]).to_bytes(4, "little", signed=True) for index in range(active_size)
        )
        template_base64 = b64encode(raw).decode("ascii") if any(byte != 0 for byte in raw) else None
        return EnrollData1Result(
            privilege=int(privilege.value),
            password_or_card=int(password.value),
            backup_number=backup_number,
            template_base64=template_base64,
        )

    def try_get_enroll_data1(self, machine_number: int, user_id: int, backup_number: int) -> EnrollData1Result | None:
        try:
            return self.get_enroll_data1(machine_number, user_id, backup_number)
        except MachineSdkError:
            return None

    def get_device_model(self, machine_number: int) -> DeviceModelInfo:
        is_big_user_id = self._long_t(0)
        company_type = self._long_t(0)
        machine_type = self._long_t(0)
        machine_version = self._long_t(0)
        ok = bool(
            self._dll._GetDeviceModel(
                machine_number,
                ctypes.byref(is_big_user_id),
                ctypes.byref(company_type),
                ctypes.byref(machine_type),
                ctypes.byref(machine_version),
            )
        )
        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "GetDeviceModel failed"))
        return DeviceModelInfo(
            is_big_user_id=bool(is_big_user_id.value),
            company_type=int(company_type.value),
            machine_type=int(machine_type.value),
            machine_version=int(machine_version.value),
        )

    def get_device_details(self, machine_number: int) -> dict[str, Any]:
        request_xml = self.xml_add_string("", "REQUEST", "GetDeviceDetails")
        request_xml = self.xml_add_string(request_xml, "MSGTYPE", "request")
        request_xml = self.xml_add_int(request_xml, "MachineID", machine_number)
        response_xml = self.general_operation_xml(machine_number, request_xml)

        int_tags = ("STN", "UserCnt", "FpCnt", "FaceCnt", "LogCnt", "EnrollSlot")
        string_tags = ("PdName", "Manuf", "FW", "SerialNo", "MAC", "IPAddress")
        parsed: dict[str, Any] = {}
        for tag in int_tags:
            try:
                parsed[tag] = self.xml_parse_int(response_xml, tag)
            except (MachineSdkError, OSError):
                try:
                    parsed[tag] = self.xml_parse_long(response_xml, tag)
                except (MachineSdkError, OSError):
                    parsed[tag] = None
        for tag in string_tags:
            try:
                parsed[tag] = self.xml_parse_string(response_xml, tag)
            except (MachineSdkError, OSError):
                parsed[tag] = None
        return {"request_xml": request_xml, "response_xml": response_xml, "parsed": parsed}

    def delete_enroll_data(
        self,
        machine_number: int,
        user_id: int,
        *,
        e_machine_number: int = 1,
        backup_number: int = 0,
    ) -> None:
        ok = bool(
            self._dll._DeleteEnrollData(
                machine_number,
                user_id,
                e_machine_number,
                backup_number,
            )
        )
        if not ok:
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"DeleteEnrollData failed for user_id={user_id}",
                )
            )

    def get_device_time(self, machine_number: int) -> datetime:
        year = self._long_t(0)
        month = self._long_t(0)
        day = self._long_t(0)
        hour = self._long_t(0)
        minute = self._long_t(0)
        second = self._long_t(0)
        _day_of_week = self._long_t(0)

        ok = bool(
            self._dll._GetDeviceTime(
                machine_number,
                ctypes.byref(year),
                ctypes.byref(month),
                ctypes.byref(day),
                ctypes.byref(hour),
                ctypes.byref(minute),
                ctypes.byref(second),
                ctypes.byref(_day_of_week),
            )
        )
        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "GetDeviceTime failed"))

        return datetime(
            int(year.value),
            int(month.value),
            int(day.value),
            int(hour.value),
            int(minute.value),
            int(second.value),
        )

    def set_user_name(self, machine_number: int, user_id: int, user_name: str) -> None:
        name_ptr = self._alloc_bstr(user_name)
        try:
            ok = bool(self._dll._SetUserName1(machine_number, user_id, ctypes.byref(name_ptr)))
        finally:
            self._free_bstr(name_ptr)
        if not ok:
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"SetUserName1 failed for user_id={user_id}",
                )
            )

    def set_user_info(
        self,
        machine_number: int,
        user_id: int,
        timezone1: int,
        timezone2: int,
        group_no: int,
    ) -> str:
        xml = ""
        xml = self.xml_add_string(xml, "REQUEST", "SetUserInfo")
        xml = self.xml_add_string(xml, "MSGTYPE", "request")
        xml = self.xml_add_int(xml, "MachineID", machine_number)
        xml = self.xml_add_int(xml, "UserID", user_id)
        xml = self.xml_add_int(xml, "Timezone1", timezone1)
        xml = self.xml_add_int(xml, "Timezone2", timezone2)
        xml = self.xml_add_int(xml, "GroupNo", group_no)
        return self.general_operation_xml(machine_number, xml)

    def try_set_user_info(
        self,
        machine_number: int,
        user_id: int,
        timezone1: int,
        timezone2: int,
        group_no: int,
    ) -> bool:
        try:
            self.set_user_info(machine_number, user_id, timezone1, timezone2, group_no)
        except MachineSdkError as exc:
            if "(code=5)" in str(exc):
                return False
            raise
        return True

    def set_enroll_data1(
        self,
        machine_number: int,
        user_id: int,
        backup_number: int,
        privilege: int,
        password_or_card: int,
    ) -> None:
        template = (self._long_t * 1)(0)
        ok = bool(
            self._dll._SetEnrollData1(
                machine_number,
                user_id,
                backup_number,
                privilege,
                ctypes.cast(template, ctypes.POINTER(self._long_t)),
                password_or_card,
            )
        )
        if not ok:
            raise MachineSdkError(
                self._format_last_error(
                    machine_number,
                    f"SetEnrollData1 failed for user_id={user_id} backup={backup_number}",
                )
            )

    def set_enroll_data_card(
        self,
        machine_number: int,
        user_id: int,
        card_num: int,
        *,
        privilege: int = 0,
        backup_number: int = 11,
    ) -> None:
        self.set_enroll_data1(
            machine_number,
            user_id,
            backup_number,
            privilege,
            card_num,
        )

    def general_operation_xml(self, machine_number: int, request_xml: str) -> str:
        xml_ptr = self._alloc_bstr(request_xml)
        try:
            ok = bool(self._dll._GeneralOperationXML(machine_number, ctypes.byref(xml_ptr)))
            response_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)

        if not ok:
            raise MachineSdkError(self._format_last_error(machine_number, "GeneralOperationXML failed"))
        return response_xml

    def xml_add_string(self, xml: str, tag: str, value: str) -> str:
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(self._dll._XML_AddString(ctypes.byref(xml_ptr), tag, value))
            out_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)

        if not ok:
            raise MachineSdkError(f"XML_AddString failed for tag={tag}")
        return out_xml

    def xml_add_int(self, xml: str, tag: str, value: int) -> str:
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(self._dll._XML_AddInt(ctypes.byref(xml_ptr), tag, value))
            out_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)

        if not ok:
            raise MachineSdkError(f"XML_AddInt failed for tag={tag}")
        return out_xml

    def xml_add_long(self, xml: str, tag: str, value: int) -> str:
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(self._dll._XML_AddLong(ctypes.byref(xml_ptr), tag, int(value)))
            out_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)
        if not ok:
            raise MachineSdkError(f"XML_AddLong failed for tag={tag}")
        return out_xml

    def xml_add_boolean(self, xml: str, tag: str, value: bool) -> str:
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(self._dll._XML_AddBoolean(ctypes.byref(xml_ptr), tag, 1 if value else 0))
            out_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)
        if not ok:
            raise MachineSdkError(f"XML_AddBoolean failed for tag={tag}")
        return out_xml

    def xml_add_binary_byte(self, xml: str, tag: str, data: bytes) -> str:
        payload = bytes(data or b"")
        buffer = (ctypes.c_ubyte * len(payload))(*payload) if payload else None
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(
                self._dll._XML_AddBinaryByte(
                    ctypes.byref(xml_ptr),
                    tag,
                    buffer,
                    len(payload),
                )
            )
            out_xml = self._bstr_to_string(xml_ptr)
        finally:
            self._free_bstr(xml_ptr)
        if not ok:
            raise MachineSdkError(f"XML_AddBinaryByte failed for tag={tag}")
        return out_xml

    def xml_parse_string(self, xml: str, tag: str) -> str:
        xml_ptr = self._alloc_bstr(xml)
        value_ptr = self._bstr_t()
        try:
            ok = bool(self._dll._XML_ParseString(ctypes.byref(xml_ptr), tag, ctypes.byref(value_ptr)))
            value = self._bstr_to_string(value_ptr)
        finally:
            self._free_bstr(xml_ptr)
            self._free_bstr(value_ptr)
        if not ok:
            raise MachineSdkError(f"XML_ParseString failed for tag={tag}")
        return value

    def xml_parse_int(self, xml: str, tag: str) -> int:
        xml_ptr = self._alloc_bstr(xml)
        try:
            value = int(self._dll._XML_ParseInt(ctypes.byref(xml_ptr), tag))
        finally:
            self._free_bstr(xml_ptr)
        return value

    def xml_parse_long(self, xml: str, tag: str) -> int:
        xml_ptr = self._alloc_bstr(xml)
        try:
            value = int(self._dll._XML_ParseLong(ctypes.byref(xml_ptr), tag))
        finally:
            self._free_bstr(xml_ptr)
        return value

    def xml_parse_boolean(self, xml: str, tag: str) -> bool:
        xml_ptr = self._alloc_bstr(xml)
        try:
            value = bool(self._dll._XML_ParseBoolean(ctypes.byref(xml_ptr), tag))
        finally:
            self._free_bstr(xml_ptr)
        return value

    def xml_parse_binary_byte_base64(self, xml: str, tag: str, length: int) -> str:
        safe_len = max(1, int(length))
        buffer = (ctypes.c_ubyte * safe_len)()
        xml_ptr = self._alloc_bstr(xml)
        try:
            ok = bool(self._dll._XML_ParseBinaryByte(ctypes.byref(xml_ptr), tag, buffer, safe_len))
        finally:
            self._free_bstr(xml_ptr)
        if not ok:
            raise MachineSdkError(f"XML_ParseBinaryByte failed for tag={tag}")
        return b64encode(bytes(buffer)).decode("ascii")

    # Backward-compatible private aliases used by existing code.
    def _xml_add_string(self, xml: str, tag: str, value: str) -> str:
        return self.xml_add_string(xml, tag, value)

    def _xml_add_int(self, xml: str, tag: str, value: int) -> str:
        return self.xml_add_int(xml, tag, value)

    def _alloc_bstr(self, value: str) -> ctypes.c_void_p:
        # SysAllocString may come back as a plain integer pointer value.
        # Wrap it as c_void_p so ctypes.byref(...) works reliably.
        raw_ptr = self._ole.SysAllocString(value or "")
        ptr = self._bstr_t(raw_ptr)
        if not ptr and value:
            raise MachineSdkError("SysAllocString failed.")
        return ptr

    def _free_bstr(self, value: ctypes.c_void_p) -> None:
        if value:
            self._ole.SysFreeString(value)

    @staticmethod
    def _bstr_to_string(value: ctypes.c_void_p) -> str:
        if not value:
            return ""
        return ctypes.wstring_at(value)

    def _format_last_error(self, machine_number: int, message: str) -> str:
        code = self.last_error(machine_number)
        if code is None:
            return message
        return f"{message} (code={code})"
