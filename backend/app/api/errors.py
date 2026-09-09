"""Consistent API error payloads."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.services.catalogs import CatalogError


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


async def catalog_error_handler(_: Request, exc: CatalogError) -> JSONResponse:
    status_code = 404 if exc.args and exc.args[0].endswith("not found.") else 409
    return error_response(status_code, "catalog_error", str(exc))


async def integrity_error_handler(_: Request, exc: IntegrityError) -> JSONResponse:
    return error_response(409, "integrity_error", "The requested change violates a database constraint.")


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(422, "validation_error", "Request validation failed.")
