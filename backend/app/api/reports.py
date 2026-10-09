from typing import List
import os
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User, Search, SearchResult, Report, SearchDoc, ReportDoc
from app.schemas.schemas import ReportOut
from app.services.report_service import generate_pdf_report

router = APIRouter(prefix="/reports", tags=["Reports"])

@router.post("/{search_id}", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def create_report_for_search(
    search_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Generate a downloadable PDF report for a search result."""
    search_obj = None
    results = []

    # 1. Check MongoDB SearchDoc
    try:
        search_doc = await SearchDoc.find_one(SearchDoc.id == search_id)
        if search_doc:
            if str(search_doc.user_id) != str(current_user.id):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access.")
            search_obj = search_doc
            results = search_doc.results
    except HTTPException:
        raise
    except Exception:
        pass

    # 2. Check SQL Search
    if not search_obj and db:
        search_sql = db.query(Search).filter(Search.id == search_id).first()
        if search_sql:
            if str(search_sql.user_id) != str(current_user.id):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access.")
            search_obj = search_sql
            results = (
                db.query(SearchResult)
                .filter(SearchResult.search_id == search_id)
                .order_by(SearchResult.rank.asc())
                .all()
            )

    if not search_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search record not found.")

    pdf_path = generate_pdf_report(search_obj, results)

    # Save report entry
    try:
        r_doc = ReportDoc(
            user_id=str(current_user.id),
            search_id=search_id,
            report_path=pdf_path
        )
        await r_doc.insert()
        return ReportOut(
            id=str(r_doc.id),
            search_id=r_doc.search_id,
            report_path=r_doc.report_path,
            created_at=r_doc.created_at
        )
    except Exception:
        pass

    if db:
        report = Report(
            user_id=str(current_user.id),
            search_id=search_id,
            report_path=pdf_path
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return ReportOut.model_validate(report)

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to save report metadata.")

@router.get("", response_model=List[ReportOut])
async def get_user_reports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve report catalog for the current user."""
    try:
        report_docs = await ReportDoc.find(ReportDoc.user_id == str(current_user.id)).sort("-created_at").to_list()
        if report_docs:
            return [
                ReportOut(
                    id=str(r.id),
                    search_id=r.search_id,
                    report_path=r.report_path,
                    created_at=r.created_at
                ) for r in report_docs
            ]
    except Exception:
        pass

    if db:
        reports = (
            db.query(Report)
            .filter(Report.user_id == current_user.id)
            .order_by(Report.created_at.desc())
            .all()
        )
        return [ReportOut.model_validate(r) for r in reports]
    return []

@router.get("/{report_id}/download")
async def download_report_file(
    report_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Download generated PDF report file."""
    report_path = None
    user_id = None

    try:
        rd = await ReportDoc.find_one(ReportDoc.id == report_id)
        if rd:
            user_id = str(rd.user_id)
            report_path = rd.report_path
    except Exception:
        pass

    if not report_path and db:
        report = db.query(Report).filter(Report.id == report_id).first()
        if report:
            user_id = str(report.user_id)
            report_path = report.report_path

    if not report_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

    if user_id != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access.")

    if not os.path.exists(report_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PDF report file missing on disk.")

    return FileResponse(
        path=report_path,
        media_type="application/pdf",
        filename=os.path.basename(report_path)
    )
