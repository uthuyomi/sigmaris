# 役割: 移動計画の FastAPI HTTP ルートを定義する。

from fastapi import APIRouter, Header, HTTPException
from app.schemas.mobility import MobilityPlanRequest
from app.services.google_maps import (
    RouteLookupError,
    get_simple_route_plan,
)
from app.services.supabase_rest import get_current_user

router = APIRouter(prefix="/api/mobility", tags=["mobility"])


def _require_jwt(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Missing bearer token."})
    return authorization.removeprefix("Bearer ").strip()


@router.post("/plan")
async def mobility_plan(
    input: MobilityPlanRequest,
    authorization: str | None = Header(default=None),
):
    jwt = _require_jwt(authorization)
    await get_current_user(jwt)

    try:
        plan = await get_simple_route_plan(
            origin=input.origin,
            destination=input.destination,
            arrival_time_iso=input.arrival_time_iso,
            mode=input.travel_mode,
        )

        return {"ok": True, "plan": plan.model_dump(by_alias=True)}
    except RouteLookupError as error:
        raise HTTPException(
            status_code=400,
            detail={
                "error": str(error),
                "routeLookup": {
                    "status": error.status,
                    "resolution": error.resolution.model_dump(by_alias=True)
                    if error.resolution
                    else None,
                },
            },
        ) from error
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=500, detail={"error": str(error)}) from error
