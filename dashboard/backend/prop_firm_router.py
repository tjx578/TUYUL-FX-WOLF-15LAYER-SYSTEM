from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/prop-firm", tags=["prop-firm"])

@router.get("/{account_id}/status")
def get_status(account_id: str):
    # bind to risk guard output; do not create direction/verdict
    return {"allowed": True, "code": "ALLOW", "severity": "LOW", "details": f"{account_id} compliant"}

@router.get("/{account_id}/phase")
def get_phase(account_id: str):
    return {"phase_name": "PHASE_1", "progress_percent": 0.0}