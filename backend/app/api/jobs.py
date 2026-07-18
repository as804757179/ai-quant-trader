from uuid import UUID

from fastapi import APIRouter, Request

from app.core.auth import get_request_principal
from app.core.response import error, ok
from app.jobs.service import AsyncJobError
from app.jobs.operations import OperationJobService


router = APIRouter()


@router.get("/{job_id}")
async def get_operation_job(job_id: UUID, request: Request):
    service = OperationJobService()
    try:
        return ok(await service.get_status(str(job_id), get_request_principal(request)))
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)


@router.get("/{job_id}/result")
async def get_operation_job_result(job_id: UUID, request: Request):
    service = OperationJobService()
    try:
        return ok(await service.get_result(str(job_id), get_request_principal(request)))
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)


@router.post("/{job_id}/cancel")
async def cancel_operation_job(job_id: UUID, request: Request):
    service = OperationJobService()
    try:
        return ok(await service.cancel(str(job_id), get_request_principal(request)))
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)


@router.post("/{job_id}/execute")
async def execute_operation_job(job_id: UUID, request: Request):
    service = OperationJobService()
    try:
        return ok(await service.execute(str(job_id), get_request_principal(request)))
    except AsyncJobError as exc:
        error(str(exc), exc.code, exc.status_code)
