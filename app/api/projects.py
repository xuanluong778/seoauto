from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.seo import Project, Scan
from app.models.user import User
from app.schemas.project import (
    PaginatedScanPagesResponse,
    PaginatedScansResponse,
    ProjectCreate,
    ProjectResponse,
    SEOTrendPoint,
    ScanCompareResponse,
    ScanDetailPaginatedResponse,
    ScanListItem,
)
from app.services.auth import get_current_user
from app.services.scan_compare import compare_scans


router = APIRouter(tags=["projects"])


@router.post("/projects", response_model=ProjectResponse)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProjectResponse:
    project = Project(user_id=current_user.id, domain=payload.domain.strip().lower())
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectResponse.model_validate(project)


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProjectResponse]:
    projects = (
        db.query(Project)
        .filter(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc())
        .limit(int(limit))
        .all()
    )
    return [ProjectResponse.model_validate(project) for project in projects]


@router.get("/projects/{project_id}/scans", response_model=PaginatedScansResponse)
def list_project_scans(
    project_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedScansResponse:
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    base_query = db.query(Scan).filter(Scan.project_id == project.id)
    total = base_query.count()
    scans = base_query.order_by(Scan.created_at.desc()).offset(offset).limit(limit).all()
    return PaginatedScansResponse(
        total=total,
        offset=offset,
        limit=limit,
        items=[ScanListItem.model_validate(scan) for scan in scans],
    )


@router.get("/projects/{project_id}/trend", response_model=list[SEOTrendPoint])
def project_seo_trend(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SEOTrendPoint]:
    project = db.query(Project).filter(Project.id == project_id, Project.user_id == current_user.id).first()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    scans = (
        db.query(Scan)
        .filter(Scan.project_id == project.id)
        .order_by(Scan.created_at.desc())
        .limit(30)
        .all()
    )
    scans.sort(key=lambda s: s.created_at)
    return [
        SEOTrendPoint(date=scan.created_at.isoformat(), seo_score=scan.seo_score)
        for scan in scans
    ]


@router.get("/scans/{scan_id}", response_model=ScanDetailPaginatedResponse)
def get_scan_detail(
    scan_id: int,
    page_offset: int = Query(default=0, ge=0),
    page_limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScanDetailPaginatedResponse:
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    if scan.project.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    pages_payload = []
    high = medium = low = 0
    total_pages_count = len(scan.pages)
    selected_pages = scan.pages[page_offset : page_offset + page_limit]
    for page in selected_pages:
        issue_payload = []
        for issue in page.issues:
            issue_payload.append({"type": issue.type, "severity": issue.severity, "message": issue.message})
            if issue.severity == "high":
                high += 1
            elif issue.severity == "medium":
                medium += 1
            elif issue.severity == "low":
                low += 1
        pages_payload.append(
            {
                "id": page.id,
                "url": page.url,
                "status": page.status,
                "title": page.title,
                "page_score": page.page_score,
                "issues": issue_payload,
            }
        )

    summary = {"total_issues": high + medium + low, "high": high, "medium": medium, "low": low}
    return ScanDetailPaginatedResponse(
        id=scan.id,
        project_id=scan.project_id,
        seo_score=scan.seo_score,
        total_pages=scan.total_pages,
        created_at=scan.created_at,
        pages=PaginatedScanPagesResponse(
            total_pages_count=total_pages_count,
            page_offset=page_offset,
            page_limit=page_limit,
            items=pages_payload,
        ),
        summary=summary,
    )


def _resolve_previous_scan(
    db: Session,
    current: Scan,
    previous_scan_id: int | None,
) -> tuple[Scan | None, bool]:
    """Returns (previous_scan, explicit_requested)."""
    if previous_scan_id is not None:
        prev = (
            db.query(Scan)
            .filter(
                Scan.id == previous_scan_id,
                Scan.project_id == current.project_id,
            )
            .first()
        )
        return prev, True
    prev = (
        db.query(Scan)
        .filter(
            Scan.project_id == current.project_id,
            Scan.id != current.id,
            or_(
                Scan.created_at < current.created_at,
                and_(Scan.created_at == current.created_at, Scan.id < current.id),
            ),
        )
        .order_by(Scan.created_at.desc(), Scan.id.desc())
        .first()
    )
    return prev, False


@router.get("/scans/{scan_id}/compare", response_model=ScanCompareResponse)
def compare_scan(
    scan_id: int,
    previous_scan_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ScanCompareResponse:
    current = db.query(Scan).filter(Scan.id == scan_id).first()
    if not current:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    if current.project.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    if previous_scan_id is not None and previous_scan_id == scan_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="previous_scan_id must differ from current scan",
        )

    previous, explicit = _resolve_previous_scan(db, current, previous_scan_id)
    if explicit and not previous:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Previous scan not found")
    if not previous:
        return ScanCompareResponse(
            current_scan_id=current.id,
            previous_scan_id=0,
            score_diff=0,
            issues_fixed=0,
            issues_added=0,
            pages_improved=0,
            pages_declined=0,
            message="No previous scan available for comparison.",
        )

    result = compare_scans(db, current, previous)
    return ScanCompareResponse(
        current_scan_id=result.current_scan_id,
        previous_scan_id=result.previous_scan_id,
        score_diff=result.score_diff,
        issues_fixed=result.issues_fixed,
        issues_added=result.issues_added,
        pages_improved=result.pages_improved,
        pages_declined=result.pages_declined,
        message=result.message,
    )
