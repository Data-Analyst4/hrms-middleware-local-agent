from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from attendance_relay.device_connection import resolve_device_connection
from attendance_relay.hrms_sync import (
    apply_employee_mappings,
    build_reconcile_report,
    build_sync_status,
    list_unmapped_machine_users,
)
from attendance_relay.machine_admin import (
    MachineConnectionRequest,
    MachineEmployeeDeleteRequest,
    MachineEmployeeReadRequest,
    MachineEmployeeToggleRequest,
    MachineEmployeeUpdateRequest,
    MachineEmployeesImportRequest,
    MachineSdkError,
    check_machine_connection,
    delete_employee_on_machine,
    get_employee_on_machine,
    import_employees_from_machine_to_db,
    list_available_machine_user_ids,
    toggle_employee_on_machine,
    update_employee_on_machine,
)
from attendance_relay.machine_device_profile import MachineDeviceDetectRequest, detect_device_on_machine
from attendance_relay.machine_user_detail import MachineUserDetailPullRequest, pull_user_detail_from_machine
from attendance_relay.middleware_models import (
    DeviceEmployeeSyncRequest,
    DeviceImportUsersRequest,
    DeviceScopedCommandRequest,
    EmployeeMappingBulkRequest,
)
from attendance_relay.middleware_repository import MiddlewareRepository
from attendance_relay.repository import AttendanceRepository
from attendance_relay.settings import Settings

LOGGER = logging.getLogger("attendance_relay.hrms_router")


def create_hrms_router(
    *,
    settings: Settings,
    repo: AttendanceRepository,
    middleware_repo: MiddlewareRepository,
    require_middleware_auth: Callable[[Request], JSONResponse | None],
    create_device_command_job: Callable[..., dict[str, Any]],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["hrms"])

    @router.get("/employees")
    async def list_employees(
        request: Request,
        limit: int = Query(default=500, ge=1, le=5000),
        offset: int = Query(default=0, ge=0),
        search: str | None = None,
    ) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        rows = repo.list_employee_master(limit=limit, offset=offset, search=search)
        return JSONResponse(
            {
                "total": repo.count_employee_master(),
                "loaded": len(rows),
                "offset": offset,
                "limit": limit,
                "rows": rows,
            },
            status_code=200,
        )

    @router.get("/employees/{employee_code}")
    async def get_employee(employee_code: str, request: Request) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        row = repo.find_employee_master(employee_code)
        if not row:
            return JSONResponse({"error": f"employee_code not found: {employee_code}"}, status_code=404)
        return JSONResponse(row, status_code=200)

    @router.get("/sync-status")
    async def sync_status(request: Request) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        payload = build_sync_status(repo=repo, middleware_repo=middleware_repo)
        payload["attendance_storage"] = (
            "local_db_only" if not settings.outbound_relay_enabled else "local_db_and_outbound_relay"
        )
        payload["outbound_relay_enabled"] = settings.outbound_relay_enabled
        return JSONResponse(payload, status_code=200)

    @router.get("/mappings/unmapped")
    async def unmapped_users(
        request: Request,
        device_id: str | None = None,
        machine_ip: str | None = None,
        limit: int = Query(default=5000, ge=1, le=50000),
    ) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        rows = list_unmapped_machine_users(
            repo,
            device_id=(device_id or None),
            machine_ip=(machine_ip or None),
            limit=limit,
        )
        return JSONResponse({"loaded": len(rows), "rows": rows}, status_code=200)

    @router.get("/mappings/reconcile")
    async def reconcile_mappings(
        request: Request,
        device_id: str = Query(..., min_length=1),
    ) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            device = middleware_repo.get_device(device_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        report = build_reconcile_report(
            repo,
            device_id=device_id,
            machine_ip=str(device.get("ip") or ""),
        )
        return JSONResponse(report, status_code=200)

    @router.post("/devices/{device_id}/mappings/bulk")
    async def bulk_map_users(
        device_id: str,
        request: Request,
        payload: EmployeeMappingBulkRequest,
    ) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            middleware_repo.get_device(device_id)
            result = apply_employee_mappings(
                repo,
                device_id=device_id,
                mappings=[item.model_dump() for item in payload.mappings],
                overwrite_names=payload.overwrite_names,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(result, status_code=200)

    @router.get("/devices/{device_id}")
    async def get_device(device_id: str, request: Request) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            device = middleware_repo.get_device(device_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        caps = repo.get_device_capabilities(
            machine_ip=str(device.get("ip") or ""),
            machine_port=int(device.get("port") or 5005),
            device_id=device_id,
        )
        return JSONResponse({"device": device, "capabilities": caps}, status_code=200)

    @router.post("/devices/{device_id}/live/test-connection")
    async def device_test_connection(device_id: str, request: Request) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            _device, resolved = resolve_device_connection(
                middleware_repo=middleware_repo,
                attendance_repo=repo,
                settings=settings,
                device_id=device_id,
            )
            from attendance_relay.machine_admin import MachineConnectionRequest

            result = check_machine_connection(
                settings=settings,
                request=MachineConnectionRequest(
                    machine_ip=resolved.machine_ip,
                    machine_port=resolved.machine_port,
                    machine_password=resolved.machine_password,
                    machine_number=resolved.machine_number,
                ),
            )
            result["device_id"] = device_id
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @router.get("/devices/{device_id}/live/available-user-ids")
    async def device_available_user_ids(
        device_id: str,
        request: Request,
        limit: int = Query(default=40, ge=1, le=200),
    ) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            _device, resolved = resolve_device_connection(
                middleware_repo=middleware_repo,
                attendance_repo=repo,
                settings=settings,
                device_id=device_id,
            )
            result = list_available_machine_user_ids(
                settings=settings,
                request=MachineConnectionRequest(
                    machine_ip=resolved.machine_ip,
                    machine_port=resolved.machine_port,
                    machine_password=resolved.machine_password,
                    machine_number=resolved.machine_number,
                ),
                limit=limit,
            )
            result["device_id"] = device_id
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @router.post("/devices/{device_id}/live/detect")
    async def device_detect(device_id: str, request: Request) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            _device, resolved = resolve_device_connection(
                middleware_repo=middleware_repo,
                attendance_repo=repo,
                settings=settings,
                device_id=device_id,
            )
            detect_request = MachineDeviceDetectRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                device_id=device_id,
                store_to_db=True,
            )
            result = detect_device_on_machine(repo=repo, settings=settings, request=detect_request)
            stn = result.get("recommended_machine_number")
            if stn:
                middleware_repo.update_device_machine_number(device_id, int(stn))
            result["device_id"] = device_id
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @router.post("/devices/{device_id}/live/import-users")
    async def device_import_users(
        device_id: str,
        request: Request,
        payload: DeviceImportUsersRequest,
    ) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            _device, resolved = resolve_device_connection(
                middleware_repo=middleware_repo,
                attendance_repo=repo,
                settings=settings,
                device_id=device_id,
            )
            import_request = MachineEmployeesImportRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                device_id=device_id,
                include_user_names=payload.include_user_names,
                overwrite_existing_names=payload.overwrite_existing_names,
                dry_run=payload.dry_run,
                limit=payload.limit,
            )
            result = import_employees_from_machine_to_db(repo=repo, settings=settings, request=import_request)
            if not payload.dry_run:
                middleware_repo.mark_device_sync(device_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @router.put("/devices/{device_id}/live/employees/{employee_code}")
    async def device_sync_employee(
        device_id: str,
        employee_code: str,
        request: Request,
        payload: DeviceEmployeeSyncRequest,
    ) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            _device, resolved = resolve_device_connection(
                middleware_repo=middleware_repo,
                attendance_repo=repo,
                settings=settings,
                device_id=device_id,
            )
            sync_request = MachineEmployeeUpdateRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                user_id=payload.user_id,
                user_name=payload.user_name,
                card_no=payload.card_no,
                timezone1=payload.timezone1,
                timezone2=payload.timezone2,
                group_no=payload.group_no,
                enable=payload.enable,
                all_slots=payload.all_slots,
            )
            result = update_employee_on_machine(
                repo=repo,
                settings=settings,
                employee_code=employee_code,
                request=sync_request,
            )
            middleware_repo.mark_device_sync(device_id)
            result["device_id"] = device_id
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @router.post("/devices/{device_id}/live/employees/{employee_code}/read")
    async def device_read_employee(device_id: str, employee_code: str, request: Request) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            _device, resolved = resolve_device_connection(
                middleware_repo=middleware_repo,
                attendance_repo=repo,
                settings=settings,
                device_id=device_id,
            )
            read_request = MachineEmployeeReadRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
            )
            result = get_employee_on_machine(
                repo=repo,
                settings=settings,
                employee_code=employee_code,
                request=read_request,
            )
            result["device_id"] = device_id
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @router.post("/devices/{device_id}/live/employees/{employee_code}/pull-detail")
    async def device_pull_detail(
        device_id: str,
        employee_code: str,
        request: Request,
        store_to_db: bool = True,
    ) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            _device, resolved = resolve_device_connection(
                middleware_repo=middleware_repo,
                attendance_repo=repo,
                settings=settings,
                device_id=device_id,
            )
            pull_request = MachineUserDetailPullRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                device_id=device_id,
                store_to_db=store_to_db,
            )
            result = pull_user_detail_from_machine(
                repo=repo,
                settings=settings,
                request=pull_request,
                employee_code=employee_code,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @router.post("/devices/{device_id}/live/employees/{employee_code}/enable")
    async def device_enable_sync(device_id: str, employee_code: str, request: Request) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            _device, resolved = resolve_device_connection(
                middleware_repo=middleware_repo,
                attendance_repo=repo,
                settings=settings,
                device_id=device_id,
            )
            toggle_request = MachineEmployeeToggleRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                all_slots=True,
            )
            result = toggle_employee_on_machine(
                repo=repo,
                settings=settings,
                employee_code=employee_code,
                enabled=True,
                request=toggle_request,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @router.post("/devices/{device_id}/live/employees/{employee_code}/disable")
    async def device_disable_sync(device_id: str, employee_code: str, request: Request) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            _device, resolved = resolve_device_connection(
                middleware_repo=middleware_repo,
                attendance_repo=repo,
                settings=settings,
                device_id=device_id,
            )
            toggle_request = MachineEmployeeToggleRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                all_slots=True,
            )
            result = toggle_employee_on_machine(
                repo=repo,
                settings=settings,
                employee_code=employee_code,
                enabled=False,
                request=toggle_request,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @router.post("/devices/{device_id}/live/employees/{employee_code}/delete")
    async def device_delete_employee_sync(device_id: str, employee_code: str, request: Request) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        try:
            _device, resolved = resolve_device_connection(
                middleware_repo=middleware_repo,
                attendance_repo=repo,
                settings=settings,
                device_id=device_id,
            )
            delete_request = MachineEmployeeDeleteRequest(
                machine_ip=resolved.machine_ip,
                machine_port=resolved.machine_port,
                machine_password=resolved.machine_password,
                machine_number=resolved.machine_number,
                all_slots=True,
            )
            result = delete_employee_on_machine(
                repo=repo,
                settings=settings,
                employee_code=employee_code,
                request=delete_request,
            )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except MachineSdkError as exc:
            return JSONResponse({"error": str(exc)}, status_code=502)
        return JSONResponse(result, status_code=200)

    @router.post("/devices/{device_id}/employees/{employee_code}/sync-queue")
    async def device_sync_queue(
        device_id: str,
        employee_code: str,
        request: Request,
        payload: DeviceScopedCommandRequest,
    ) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        cmd_payload = {**payload.payload, "employee_code": employee_code}
        command = create_device_command_job(
            device_id=device_id,
            command_type="employee.sync_one",
            request_id=payload.request_id,
            payload_data=cmd_payload,
            priority=payload.priority,
        )
        return JSONResponse(command, status_code=202)

    @router.get("/attendance/local-punches")
    async def local_punches(
        request: Request,
        employee_code: str | None = None,
        device_sn: str | None = None,
        since: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> JSONResponse:
        denied = require_middleware_auth(request)
        if denied:
            return denied
        rows = repo.list_attendance(
            limit=limit,
            employee_code=(employee_code or None),
            device_sn=(device_sn or None),
            since=(since or None),
        )
        return JSONResponse(
            {
                "storage_mode": "local_db_only" if not settings.outbound_relay_enabled else "local_db_and_outbound_relay",
                "total": repo.get_attendance_total(),
                "loaded": len(rows),
                "rows": rows,
            },
            status_code=200,
        )

    return router
