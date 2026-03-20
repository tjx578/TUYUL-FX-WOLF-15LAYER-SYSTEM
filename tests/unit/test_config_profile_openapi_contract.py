from __future__ import annotations

from fastapi import FastAPI

from api.config_profile_router import router as config_profile_router


_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
_REQUIRED_RESPONSES = {"200", "404", "409", "422"}
_ERROR_RESPONSE_REF = "#/components/schemas/ErrorResponse"
_COMPONENT_REF_PREFIX = "#/components/schemas/"


def _response_ref(operation: dict, status_code: str) -> str | None:
    response = operation.get("responses", {}).get(status_code, {})
    content = response.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})
    ref = schema.get("$ref")
    return str(ref) if isinstance(ref, str) else None


def test_config_profile_openapi_operations_expose_required_response_codes() -> None:
    app = FastAPI()
    app.include_router(config_profile_router)

    schema = app.openapi()
    paths = schema.get("paths", {})

    config_paths = {
        path: item
        for path, item in paths.items()
        if path.startswith("/api/v1/config/profile") or path.startswith("/api/v1/config/profiles")
    }

    assert config_paths, "Expected config profile paths to exist in OpenAPI schema"

    for path, path_item in config_paths.items():
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS:
                continue
            responses = operation.get("responses", {})
            missing = _REQUIRED_RESPONSES - set(responses.keys())
            assert not missing, f"{method.upper()} {path} missing OpenAPI responses: {sorted(missing)}"

            success_ref = _response_ref(operation, "200")
            assert success_ref is not None, f"{method.upper()} {path} response 200 must use a $ref schema"
            assert success_ref.startswith(_COMPONENT_REF_PREFIX), (
                f"{method.upper()} {path} response 200 must reference a component schema"
            )
            assert success_ref != _ERROR_RESPONSE_REF, (
                f"{method.upper()} {path} response 200 must not reference ErrorResponse"
            )

            for status in ("404", "409", "422"):
                assert _response_ref(operation, status) == _ERROR_RESPONSE_REF, (
                    f"{method.upper()} {path} response {status} must reference {_ERROR_RESPONSE_REF}"
                )


def test_config_profile_openapi_error_response_component_shape() -> None:
    app = FastAPI()
    app.include_router(config_profile_router)

    schema = app.openapi()
    components = schema.get("components", {}).get("schemas", {})
    assert "ErrorResponse" in components, "OpenAPI components must define ErrorResponse"

    error_schema = components["ErrorResponse"]
    properties = error_schema.get("properties", {})
    assert "detail" in properties, "ErrorResponse must contain detail field"
