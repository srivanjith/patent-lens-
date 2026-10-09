from typing import List, Optional
from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User, Patent, SavedPatent, PatentDoc, SavedPatentDoc
from app.schemas.schemas import PatentOut, SavedPatentOut, SavePatentRequest, CreateCustomPatentRequest
from ml.embedding_service import embedding_service
from ml.preprocessing import prepare_combined_text

router = APIRouter(prefix="/patents", tags=["Patents"])

@router.get("/saved", response_model=List[SavedPatentOut])
async def get_user_saved_patents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve all saved patents for the authenticated user."""
    try:
        saved_docs = await SavedPatentDoc.find(SavedPatentDoc.user_id == current_user.id).sort("-created_at").to_list()
        if saved_docs:
            out_list = []
            for s in saved_docs:
                p_doc = await PatentDoc.find_one(PatentDoc.id == s.patent_id)
                if not p_doc:
                    p_doc = await PatentDoc.find_one(PatentDoc.patent_number == s.patent_id)
                if p_doc:
                    patent_out = PatentOut(
                        id=p_doc.id or s.patent_id,
                        patent_number=p_doc.patent_number or s.patent_id,
                        title=p_doc.title or "Saved Patent",
                        abstract=p_doc.abstract or "",
                        description=p_doc.description or "",
                        claims=p_doc.claims,
                        inventors=p_doc.inventors or "Unknown",
                        assignee=p_doc.assignee or "Independent",
                        publication_date=p_doc.publication_date or "2024-01-01",
                        domain=p_doc.domain or "General",
                        source_url=p_doc.source_url,
                        source_type=p_doc.source_type or "DATABASE",
                        source_status=p_doc.source_status or "DATABASE",
                        document_type=p_doc.document_type or "DATABASE RECORD",
                        lens_id=p_doc.lens_id,
                        filing_date=p_doc.filing_date,
                        earliest_priority_date=p_doc.earliest_priority_date,
                        simple_family_id=p_doc.simple_family_id,
                        simple_family_size=p_doc.simple_family_size,
                        extended_family_size=p_doc.extended_family_size,
                        data_quality_status=p_doc.data_quality_status,
                        cpc_codes=p_doc.cpc_codes,
                        ipc_codes=p_doc.ipc_codes,
                        jurisdiction=p_doc.jurisdiction,
                        created_at=p_doc.created_at
                    )
                    out_list.append(SavedPatentOut(
                        id=str(s.id),
                        patent_id=s.patent_id,
                        notes=s.notes,
                        created_at=s.created_at,
                        patent=patent_out
                    ))
            return out_list
    except Exception:
        pass

    if db:
        saved = (
            db.query(SavedPatent)
            .filter(SavedPatent.user_id == current_user.id)
            .order_by(SavedPatent.created_at.desc())
            .all()
        )
        return [SavedPatentOut.model_validate(s) for s in saved]
    return []

@router.get("/{patent_id}", response_model=PatentOut)
async def get_patent_details(patent_id: str, db: Session = Depends(get_db)):
    """Get single patent details by patent_id or patent_number."""
    try:
        doc = await PatentDoc.find_one(PatentDoc.id == patent_id)
        if not doc:
            doc = await PatentDoc.find_one(PatentDoc.patent_number == patent_id)
        if doc:
            return PatentOut(
                id=doc.id or patent_id,
                patent_number=doc.patent_number or patent_id,
                title=doc.title or "Patent Record",
                abstract=doc.abstract or "",
                description=doc.description or "",
                claims=doc.claims,
                inventors=doc.inventors or "Unknown",
                assignee=doc.assignee or "Independent",
                publication_date=doc.publication_date or "2024-01-01",
                domain=doc.domain or "General",
                source_url=doc.source_url,
                source_type=doc.source_type or "DATABASE",
                source_status=doc.source_status or "DATABASE",
                document_type=doc.document_type or "DATABASE RECORD",
                lens_id=doc.lens_id,
                filing_date=doc.filing_date,
                earliest_priority_date=doc.earliest_priority_date,
                simple_family_id=doc.simple_family_id,
                simple_family_size=doc.simple_family_size,
                extended_family_size=doc.extended_family_size,
                data_quality_status=doc.data_quality_status,
                cpc_codes=doc.cpc_codes,
                ipc_codes=doc.ipc_codes,
                jurisdiction=doc.jurisdiction,
                created_at=doc.created_at
            )
    except Exception:
        pass

    if db:
        patent = db.query(Patent).filter((Patent.id == patent_id) | (Patent.patent_number == patent_id)).first()
        if patent:
            return PatentOut.model_validate(patent)
            
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patent not found.")

@router.post("/{patent_id}/save", response_model=SavedPatentOut)
async def save_patent(
    patent_id: str,
    request: SavePatentRequest = SavePatentRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Save a patent to authenticated user's saved list under their specific logged-in user_id."""
    patent_doc = None
    try:
        patent_doc = await PatentDoc.find_one(PatentDoc.id == patent_id)
        if not patent_doc:
            patent_doc = await PatentDoc.find_one(PatentDoc.patent_number == patent_id)
    except Exception:
        pass

    patent_sql = None
    if not patent_doc and db:
        patent_sql = db.query(Patent).filter((Patent.id == patent_id) | (Patent.patent_number == patent_id)).first()

    if not patent_doc and not patent_sql:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patent not found.")

    target_patent_id: str = (patent_doc.id if patent_doc and patent_doc.id else (patent_sql.id if patent_sql and patent_sql.id else patent_id))

    try:
        p_doc = patent_doc or await PatentDoc.find_one(PatentDoc.id == target_patent_id)
        if not p_doc:
            p_doc = await PatentDoc.find_one(PatentDoc.patent_number == target_patent_id)

        p_out = PatentOut(
            id=p_doc.id if (p_doc and p_doc.id) else target_patent_id,
            patent_number=p_doc.patent_number if (p_doc and p_doc.patent_number) else target_patent_id,
            title=p_doc.title if p_doc else "Saved Patent",
            abstract=p_doc.abstract if p_doc else "",
            description=p_doc.description if p_doc else "",
            claims=p_doc.claims if p_doc else None,
            inventors=p_doc.inventors if (p_doc and p_doc.inventors) else "Unknown",
            assignee=p_doc.assignee if (p_doc and p_doc.assignee) else "Independent",
            publication_date=p_doc.publication_date if (p_doc and p_doc.publication_date) else "2024-01-01",
            domain=p_doc.domain if p_doc else "General",
            source_url=p_doc.source_url if p_doc else None,
            source_type=p_doc.source_type if p_doc else "DATABASE",
            source_status=p_doc.source_status if p_doc else "DATABASE",
            document_type=p_doc.document_type if p_doc else "DATABASE RECORD",
            lens_id=p_doc.lens_id if p_doc else None,
            filing_date=p_doc.filing_date if p_doc else None,
            earliest_priority_date=p_doc.earliest_priority_date if p_doc else None,
            simple_family_id=p_doc.simple_family_id if p_doc else None,
            simple_family_size=p_doc.simple_family_size if p_doc else 1,
            extended_family_size=p_doc.extended_family_size if p_doc else 1,
            data_quality_status=p_doc.data_quality_status if p_doc else "LIMITED",
            cpc_codes=p_doc.cpc_codes if p_doc else None,
            ipc_codes=p_doc.ipc_codes if p_doc else None,
            jurisdiction=p_doc.jurisdiction if p_doc else None,
            created_at=p_doc.created_at if p_doc else datetime.now(timezone.utc)
        )

        existing_doc = await SavedPatentDoc.find_one(
            SavedPatentDoc.user_id == current_user.id,
            SavedPatentDoc.patent_id == target_patent_id
        )
        if existing_doc:
            if request.notes is not None:
                existing_doc.notes = request.notes
                await existing_doc.save()
            return SavedPatentOut(
                id=str(existing_doc.id),
                patent_id=existing_doc.patent_id,
                notes=existing_doc.notes,
                created_at=existing_doc.created_at,
                patent=p_out
            )

        new_saved_doc = SavedPatentDoc(
            user_id=current_user.id,
            patent_id=target_patent_id,
            notes=request.notes
        )
        await new_saved_doc.insert()
        return SavedPatentOut(
            id=str(new_saved_doc.id),
            patent_id=new_saved_doc.patent_id,
            notes=new_saved_doc.notes,
            created_at=new_saved_doc.created_at,
            patent=p_out
        )
    except Exception:
        pass

    if db:
        existing = (
            db.query(SavedPatent)
            .filter(SavedPatent.user_id == current_user.id, SavedPatent.patent_id == target_patent_id)
            .first()
        )
        if existing:
            if request.notes is not None:
                existing.notes = request.notes
                db.commit()
                db.refresh(existing)
            return SavedPatentOut.model_validate(existing)

        saved = SavedPatent(
            user_id=current_user.id,
            patent_id=target_patent_id,
            notes=request.notes
        )
        db.add(saved)
        db.commit()
        db.refresh(saved)
        return SavedPatentOut.model_validate(saved)

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not save patent.")

@router.delete("/{patent_id}/save")
async def unsave_patent(
    patent_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Remove a patent from authenticated user's saved patents list."""
    try:
        existing_doc = await SavedPatentDoc.find_one(
            SavedPatentDoc.user_id == current_user.id,
            SavedPatentDoc.patent_id == patent_id
        )
        if existing_doc:
            await existing_doc.delete()
            return {"success": True, "message": "Patent removed from saved list."}
    except Exception:
        pass

    if db:
        patent = db.query(Patent).filter((Patent.id == patent_id) | (Patent.patent_number == patent_id)).first()
        p_id = patent.id if patent else patent_id
        saved = (
            db.query(SavedPatent)
            .filter(SavedPatent.user_id == current_user.id, SavedPatent.patent_id == p_id)
            .first()
        )
        if saved:
            db.delete(saved)
            db.commit()
            return {"success": True, "message": "Patent removed from saved list."}

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patent not found in saved list.")

@router.post("/custom", response_model=PatentOut, status_code=status.HTTP_201_CREATED)
async def create_custom_patent(
    request: CreateCustomPatentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Save user-created custom invention into MongoDB Atlas with vector embeddings."""
    pat_number = f"US-USER-{uuid.uuid4().hex[:8].upper()}"

    combined_text = prepare_combined_text(
        title=request.title,
        problem_statement="",
        description=f"{request.abstract} {request.description}"
    )
    
    if not embedding_service.is_loaded:
        embedding_service.load_model()
        
    embedding_vec = embedding_service.generate_embedding(combined_text)
    if isinstance(embedding_vec, list):
        emb_data = embedding_vec
    else:
        emb_data = embedding_vec.tolist()

    try:
        new_doc = PatentDoc(
            patent_number=pat_number,
            title=request.title,
            abstract=request.abstract,
            description=request.description,
            inventors=request.inventors or current_user.name,
            assignee=request.assignee or "User Invention",
            publication_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            domain=request.domain,
            source_url=f"https://patentlens.ai/user/patent/{pat_number}",
            source_type="DATABASE",
            source_status="DATABASE",
            document_type="DATABASE RECORD",
            embedding=emb_data
        )
        await new_doc.insert()

        saved_doc = SavedPatentDoc(
            user_id=current_user.id,
            patent_id=new_doc.id or pat_number,
            notes="User Submitted Invention"
        )
        await saved_doc.insert()

        return PatentOut(
            id=new_doc.id or pat_number,
            patent_number=new_doc.patent_number or pat_number,
            title=new_doc.title,
            abstract=new_doc.abstract,
            description=new_doc.description,
            claims=new_doc.claims,
            inventors=new_doc.inventors or "Unknown",
            assignee=new_doc.assignee or "Independent",
            publication_date=new_doc.publication_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            domain=new_doc.domain,
            source_url=new_doc.source_url,
            source_type=new_doc.source_type or "DATABASE",
            source_status=new_doc.source_status or "DATABASE",
            document_type=new_doc.document_type or "DATABASE RECORD",
            created_at=new_doc.created_at
        )
    except Exception:
        pass

    if db:
        new_patent = Patent(
            patent_number=pat_number,
            title=request.title,
            abstract=request.abstract,
            description=request.description,
            inventors=request.inventors or current_user.name,
            assignee=request.assignee or "User Invention",
            publication_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            domain=request.domain,
            source_url=f"https://patentlens.ai/user/patent/{pat_number}",
            embedding=emb_data
        )
        db.add(new_patent)
        db.commit()
        db.refresh(new_patent)

        saved_link = SavedPatent(user_id=current_user.id, patent_id=new_patent.id, notes="User Submitted Invention")
        db.add(saved_link)
        db.commit()

        return PatentOut.model_validate(new_patent)

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create custom patent.")
