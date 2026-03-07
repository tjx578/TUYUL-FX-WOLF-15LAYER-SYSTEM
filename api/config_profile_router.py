from __future__ import annotations

from typing import Annotated, Any, Literal, NoReturn

from fastapi import HTTPException, Path, Query
from fastapi.params import Depends
from fastapi.routing import APIRouter
from pydantic import BaseModel, Field

from api.middleware.auth import verify_token
from api.middleware.governance import GovernanceContext, enforce_write_policy
from config.profile_engine import ConfigProfileEngine
from journal.audit_trail import AuditAction, AuditTrail

router: APIRouter = APIRouter(tags=["config-profile"])
profile_router: APIRouter = APIRouter(prefix="/api/v1/config/profile", tags=["config-profile"])
legacy_router: APIRouter = APIRouter(prefix="/api/v1/config/profiles", tags=["config-profile"])

_engine = ConfigProfileEngine()
_audit = AuditTrail()

_SCOPE_PATTERN = "^(global|account|prop_firm|pair)$"


def _raise_from_engine(exc: ValueError) -> NoReturn:
    message = str(exc)
    lowered = message.lower()

    if "unknown" in lowered:
        raise HTTPException(status_code=404, detail=message) from exc
    if "required" in lowered:
        raise HTTPException(status_code=422, detail=message) from exc
    if "locked" in lowered or "already exists" in lowered or "cannot" in lowered:
        raise HTTPException(status_code=409, detail=message) from exc
    raise HTTPException(status_code=400, detail=message) from exc


class ActivateProfileRequest(BaseModel):
    profile_name: str = Field(..., min_length=1)


class ConfigScopeRef(BaseModel):
    account_id: str | None = None
    prop_firm: str | None = None
    pair: str | None = None


class ProfileRecord(BaseModel):
    profile_name: str
    source: Literal["builtin", "runtime"]


class ProfilePayloadResponse(BaseModel):
    profile_name: str
    profile: dict[str, Any]


class ProfilesListResponse(BaseModel):
    active_profile: str
    profiles: list[ProfileRecord]
    profile_names: list[str]
    scopes: dict[str, list[str]]
    locked: bool


class ActiveProfileResponse(BaseModel):
    active_profile: str
    locked: bool
    effective_config: dict[str, Any]


class EffectiveProfileResponse(BaseModel):
    active_profile: str
    locked: bool
    scope: ConfigScopeRef
    effective_config: dict[str, Any]


class RevisionResponse(BaseModel):
    revision_id: int
    timestamp: str
    actor: str
    reason: str
    action: str
    diff: dict[str, Any]


class RevisionsListResponse(BaseModel):
    count: int
    revisions: list[RevisionResponse]


class OverrideResponse(BaseModel):
    scope: Literal["global", "account", "prop_firm", "pair"]
    key: str
    override: dict[str, Any]
    exists: bool | None = None


class OverrideDeleteResponse(BaseModel):
    deleted: bool
    scope: Literal["global", "account", "prop_firm", "pair"]
    key: str


class OverrideListResponse(BaseModel):
    overrides: dict[str, dict[str, dict[str, Any]]]


class LockStateResponse(BaseModel):
    active_profile: str
    locked: bool


class ProfileDeleteResponse(BaseModel):
    deleted: bool
    profile_name: str


class ProfileCreateRequest(BaseModel):
    profile_name: str = Field(..., min_length=1)
    profile: dict[str, Any]


class ProfileUpdateRequest(BaseModel):
    profile: dict[str, Any]


class ProfilePatchRequest(BaseModel):
    profile: dict[str, Any]


class OverrideUpsertRequest(BaseModel):
    scope: str = Field(..., pattern=_SCOPE_PATTERN)
    scope_key: str = Field(..., min_length=1)
    override: dict[str, Any]


class OverrideValueRequest(BaseModel):
    override: dict[str, Any]


class ConfigLockRequest(BaseModel):
    locked: bool


class ErrorResponse(BaseModel):
    detail: str | list[dict[str, Any]]


def _responses(
    success_model: type[BaseModel],
    *,
    include_404: bool = False,
    include_409: bool = False,
    include_422: bool = False,
) -> dict[int, dict[str, Any]]:
    # Keep these status codes explicit across all config-profile operations
    # to make FE/BE contract verification deterministic in OpenAPI docs.
    responses: dict[int, dict[str, Any]] = {
        200: {"description": "Success", "model": success_model},
        404: {"description": "Not Found", "model": ErrorResponse},
        409: {"description": "Conflict", "model": ErrorResponse},
        422: {"description": "Validation Error", "model": ErrorResponse},
    }
    return responses


@profile_router.get(
    "",
    dependencies=[Depends(verify_token)],
    response_model=ProfilesListResponse,
    responses=_responses(ProfilesListResponse, include_422=True),
)
@legacy_router.get(
    "",
    dependencies=[Depends(verify_token)],
    response_model=ProfilesListResponse,
    responses=_responses(ProfilesListResponse, include_422=True),
)
async def list_profiles() -> ProfilesListResponse:
    return {
        "active_profile": _engine.get_active_profile(),
        "profiles": _engine.list_profile_records(),
        "profile_names": _engine.list_profiles(),
        "scopes": _engine.list_scoped_overrides(),
        "locked": _engine.is_locked(),
    }


@profile_router.post(
    "",
    dependencies=[Depends(verify_token)],
    response_model=ProfilePayloadResponse,
    responses=_responses(ProfilePayloadResponse, include_409=True, include_422=True),
)
@legacy_router.post(
    "",
    dependencies=[Depends(verify_token)],
    response_model=ProfilePayloadResponse,
    responses=_responses(ProfilePayloadResponse, include_409=True, include_422=True),
)
async def create_profile(
    req: ProfileCreateRequest,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> ProfilePayloadResponse:
    try:
        result = _engine.create_profile(
            profile_name=req.profile_name,
            profile=req.profile,
            actor=context.actor,
            reason=context.reason,
        )
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource=f"config:profile:{result['profile_name']}",
            details={"action": "CREATE_PROFILE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.get(
    "/active",
    dependencies=[Depends(verify_token)],
    response_model=ActiveProfileResponse,
    responses=_responses(ActiveProfileResponse, include_422=True),
)
@legacy_router.get(
    "/active",
    dependencies=[Depends(verify_token)],
    response_model=ActiveProfileResponse,
    responses=_responses(ActiveProfileResponse, include_422=True),
)
async def get_active_profile() -> ActiveProfileResponse:
    return {
        "active_profile": _engine.get_active_profile(),
        "locked": _engine.is_locked(),
        "effective_config": _engine.get_effective_config(
            account_id=None,
            prop_firm=None,
            pair=None,
        ),
    }


@profile_router.get(
    "/effective",
    dependencies=[Depends(verify_token)],
    response_model=EffectiveProfileResponse,
    responses=_responses(EffectiveProfileResponse, include_422=True),
)
@legacy_router.get(
    "/effective",
    dependencies=[Depends(verify_token)],
    response_model=EffectiveProfileResponse,
    responses=_responses(EffectiveProfileResponse, include_422=True),
)
async def get_effective_profile(
    account_id: Annotated[str | None, Query()] = None,
    prop_firm: Annotated[str | None, Query()] = None,
    pair: Annotated[str | None, Query()] = None,
) -> EffectiveProfileResponse:
    return {
        "active_profile": _engine.get_active_profile(),
        "locked": _engine.is_locked(),
        "scope": {
            "account_id": account_id,
            "prop_firm": prop_firm,
            "pair": pair,
        },
        "effective_config": _engine.get_effective_config(
            account_id=account_id,
            prop_firm=prop_firm,
            pair=pair,
        ),
    }


@profile_router.get(
    "/revisions",
    dependencies=[Depends(verify_token)],
    response_model=RevisionsListResponse,
    responses=_responses(RevisionsListResponse, include_422=True),
)
@legacy_router.get(
    "/revisions",
    dependencies=[Depends(verify_token)],
    response_model=RevisionsListResponse,
    responses=_responses(RevisionsListResponse, include_422=True),
)
async def list_config_revisions(limit: Annotated[int, Query(ge=1, le=500)] = 50) -> RevisionsListResponse:
    return {
        "count": min(limit, len(_engine.list_revisions(limit=limit))),
        "revisions": _engine.list_revisions(limit=limit),
    }


@profile_router.post(
    "/active",
    dependencies=[Depends(verify_token)],
    response_model=ActiveProfileResponse,
    responses=_responses(ActiveProfileResponse, include_404=True, include_409=True, include_422=True),
)
@legacy_router.post(
    "/active",
    dependencies=[Depends(verify_token)],
    response_model=ActiveProfileResponse,
    responses=_responses(ActiveProfileResponse, include_404=True, include_409=True, include_422=True),
)
async def activate_profile(
    req: ActivateProfileRequest,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> ActiveProfileResponse:
    try:
        raw_result = _engine.activate(req.profile_name, actor=context.actor, reason=context.reason)
        result = {
            "active_profile": raw_result["active_profile"],
            "effective_config": raw_result["effective_config"],
            "locked": _engine.is_locked(),
        }
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource="config:profiles",
            details={"action": "ACTIVATE_PROFILE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.get(
    "/overrides",
    dependencies=[Depends(verify_token)],
    response_model=OverrideListResponse,
    responses=_responses(OverrideListResponse, include_404=True, include_422=True),
)
@legacy_router.get(
    "/overrides",
    dependencies=[Depends(verify_token)],
    response_model=OverrideListResponse,
    responses=_responses(OverrideListResponse, include_404=True, include_422=True),
)
async def list_overrides(
    scope: Annotated[str | None, Query(pattern=_SCOPE_PATTERN)] = None,
) -> OverrideListResponse:
    try:
        return {
            "overrides": _engine.list_overrides(scope=scope),
        }
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.get(
    "/overrides/{scope}/{scope_key}",
    dependencies=[Depends(verify_token)],
    response_model=OverrideResponse,
    responses=_responses(OverrideResponse, include_404=True, include_422=True),
)
@legacy_router.get(
    "/overrides/{scope}/{scope_key}",
    dependencies=[Depends(verify_token)],
    response_model=OverrideResponse,
    responses=_responses(OverrideResponse, include_404=True, include_422=True),
)
async def get_override(
    scope: Annotated[str, Path(pattern=_SCOPE_PATTERN)],
    scope_key: str,
) -> OverrideResponse:
    try:
        return _engine.get_override(scope, scope_key)
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.put(
    "/overrides/{scope}/{scope_key}",
    dependencies=[Depends(verify_token)],
    response_model=OverrideResponse,
    responses=_responses(OverrideResponse, include_404=True, include_409=True, include_422=True),
)
@legacy_router.put(
    "/overrides/{scope}/{scope_key}",
    dependencies=[Depends(verify_token)],
    response_model=OverrideResponse,
    responses=_responses(OverrideResponse, include_404=True, include_409=True, include_422=True),
)
async def put_override(
    scope: Annotated[str, Path(pattern=_SCOPE_PATTERN)],
    scope_key: str,
    req: OverrideValueRequest,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> OverrideResponse:
    try:
        result = _engine.upsert_override(
            scope,
            scope_key,
            req.override,
            actor=context.actor,
            reason=context.reason,
        )
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource=f"config:override:{scope}:{scope_key}",
            details={"action": "UPSERT_OVERRIDE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.delete(
    "/overrides/{scope}/{scope_key}",
    dependencies=[Depends(verify_token)],
    response_model=OverrideDeleteResponse,
    responses=_responses(OverrideDeleteResponse, include_404=True, include_409=True, include_422=True),
)
@legacy_router.delete(
    "/overrides/{scope}/{scope_key}",
    dependencies=[Depends(verify_token)],
    response_model=OverrideDeleteResponse,
    responses=_responses(OverrideDeleteResponse, include_404=True, include_409=True, include_422=True),
)
async def delete_override_by_path(
    scope: Annotated[str, Path(pattern=_SCOPE_PATTERN)],
    scope_key: str,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> OverrideDeleteResponse:
    try:
        result = _engine.delete_override(
            scope,
            scope_key,
            actor=context.actor,
            reason=context.reason,
        )
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource=f"config:override:{scope}:{scope_key}",
            details={"action": "DELETE_OVERRIDE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.post(
    "/override",
    dependencies=[Depends(verify_token)],
    response_model=OverrideResponse,
    responses=_responses(OverrideResponse, include_404=True, include_409=True, include_422=True),
)
@legacy_router.post(
    "/override",
    dependencies=[Depends(verify_token)],
    response_model=OverrideResponse,
    responses=_responses(OverrideResponse, include_404=True, include_409=True, include_422=True),
)
async def upsert_override(
    req: OverrideUpsertRequest,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> OverrideResponse:
    try:
        result = _engine.upsert_override(
            req.scope,
            req.scope_key,
            req.override,
            actor=context.actor,
            reason=context.reason,
        )
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource=f"config:override:{req.scope}:{req.scope_key}",
            details={"action": "UPSERT_OVERRIDE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.delete(
    "/override",
    dependencies=[Depends(verify_token)],
    response_model=OverrideDeleteResponse,
    responses=_responses(OverrideDeleteResponse, include_404=True, include_409=True, include_422=True),
)
@legacy_router.delete(
    "/override",
    dependencies=[Depends(verify_token)],
    response_model=OverrideDeleteResponse,
    responses=_responses(OverrideDeleteResponse, include_404=True, include_409=True, include_422=True),
)
async def delete_override(
    scope: Annotated[str, Query(pattern=_SCOPE_PATTERN)],
    scope_key: Annotated[str, Query(min_length=1)],
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> OverrideDeleteResponse:
    try:
        result = _engine.delete_override(
            scope,
            scope_key,
            actor=context.actor,
            reason=context.reason,
        )
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource=f"config:override:{scope}:{scope_key}",
            details={"action": "DELETE_OVERRIDE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.post(
    "/lock",
    dependencies=[Depends(verify_token)],
    response_model=LockStateResponse,
    responses=_responses(LockStateResponse, include_409=True, include_422=True),
)
@legacy_router.post(
    "/lock",
    dependencies=[Depends(verify_token)],
    response_model=LockStateResponse,
    responses=_responses(LockStateResponse, include_409=True, include_422=True),
)
async def lock_config(
    req: ConfigLockRequest,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> LockStateResponse:
    result = _engine.set_lock(req.locked, actor=context.actor, reason=context.reason)
    _audit.log(
        AuditAction.ORDER_MODIFIED,
        actor=context.actor,
        resource="config:lock",
        details={"action": "SET_LOCK", "reason": context.reason, "result": result},
    )
    return result


@profile_router.get(
    "/{profile_name}",
    dependencies=[Depends(verify_token)],
    response_model=ProfilePayloadResponse,
    responses=_responses(ProfilePayloadResponse, include_404=True, include_422=True),
)
@legacy_router.get(
    "/{profile_name}",
    dependencies=[Depends(verify_token)],
    response_model=ProfilePayloadResponse,
    responses=_responses(ProfilePayloadResponse, include_404=True, include_422=True),
)
async def get_profile(profile_name: str) -> ProfilePayloadResponse:
    try:
        return {
            "profile_name": profile_name.strip().lower(),
            "profile": _engine.get_profile(profile_name),
        }
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.put(
    "/{profile_name}",
    dependencies=[Depends(verify_token)],
    response_model=ProfilePayloadResponse,
    responses=_responses(ProfilePayloadResponse, include_404=True, include_409=True, include_422=True),
)
@legacy_router.put(
    "/{profile_name}",
    dependencies=[Depends(verify_token)],
    response_model=ProfilePayloadResponse,
    responses=_responses(ProfilePayloadResponse, include_404=True, include_409=True, include_422=True),
)
async def update_profile(
    profile_name: str,
    req: ProfileUpdateRequest,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> ProfilePayloadResponse:
    try:
        result = _engine.update_profile(
            profile_name=profile_name,
            profile=req.profile,
            actor=context.actor,
            reason=context.reason,
        )
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource=f"config:profile:{result['profile_name']}",
            details={"action": "UPDATE_PROFILE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.patch(
    "/{profile_name}",
    dependencies=[Depends(verify_token)],
    response_model=ProfilePayloadResponse,
    responses=_responses(ProfilePayloadResponse, include_404=True, include_409=True, include_422=True),
)
@legacy_router.patch(
    "/{profile_name}",
    dependencies=[Depends(verify_token)],
    response_model=ProfilePayloadResponse,
    responses=_responses(ProfilePayloadResponse, include_404=True, include_409=True, include_422=True),
)
async def patch_profile(
    profile_name: str,
    req: ProfilePatchRequest,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> ProfilePayloadResponse:
    try:
        result = _engine.patch_profile(
            profile_name=profile_name,
            profile_patch=req.profile,
            actor=context.actor,
            reason=context.reason,
        )
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource=f"config:profile:{result['profile_name']}",
            details={"action": "PATCH_PROFILE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        _raise_from_engine(exc)


@profile_router.delete(
    "/{profile_name}",
    dependencies=[Depends(verify_token)],
    response_model=ProfileDeleteResponse,
    responses=_responses(ProfileDeleteResponse, include_404=True, include_409=True, include_422=True),
)
@legacy_router.delete(
    "/{profile_name}",
    dependencies=[Depends(verify_token)],
    response_model=ProfileDeleteResponse,
    responses=_responses(ProfileDeleteResponse, include_404=True, include_409=True, include_422=True),
)
async def delete_profile(
    profile_name: str,
    context: Annotated[GovernanceContext, Depends(enforce_write_policy)],
) -> ProfileDeleteResponse:
    try:
        result = _engine.delete_profile(
            profile_name=profile_name,
            actor=context.actor,
            reason=context.reason,
        )
        _audit.log(
            AuditAction.ORDER_MODIFIED,
            actor=context.actor,
            resource=f"config:profile:{result['profile_name']}",
            details={"action": "DELETE_PROFILE", "reason": context.reason, "result": result},
        )
        return result
    except ValueError as exc:
        _raise_from_engine(exc)


router.include_router(profile_router)
router.include_router(legacy_router)
