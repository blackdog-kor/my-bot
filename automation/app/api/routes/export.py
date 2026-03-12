from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import Response

from app.db import export_competitor_users_csv

router = APIRouter()


@router.get("/api/export/competitor-users", tags=["Export"])
async def export_competitor_users():
    """
    competitor_users 테이블 전체를 CSV 파일로 다운로드합니다.
    브라우저에서 이 URL을 열면 파일이 내려받아지며, 엑셀에서 바로 열 수 있습니다.
    """
    csv_content = export_competitor_users_csv()
    filename = f"competitor_users_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        content=csv_content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
