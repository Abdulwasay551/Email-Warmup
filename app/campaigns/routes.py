"""
Campaign routes for campaign management
"""
from typing import List
from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import get_settings
from app.auth.dependencies import get_current_user
from app.db.models import User, WarmupCampaign, CampaignStatus
from app.campaigns import schemas, service

router = APIRouter()
settings = get_settings()
templates = Jinja2Templates(directory="templates")


@router.get("/campaigns", response_class=HTMLResponse)
async def campaigns_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Campaign list page"""
    return templates.TemplateResponse(
        "campaigns/list.html",
        {
            "request": request,
            "user": current_user,
            "settings": settings
        }
    )


@router.get("/campaigns/create", response_class=HTMLResponse)
async def create_campaign_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Campaign creation page"""
    # Load user's inboxes
    from app.inbox.service import get_user_inboxes
    inboxes = await get_user_inboxes(db, current_user.id)
    
    # Convert to dictionaries for JSON serialization
    inboxes_dict = [
        {
            "id": inbox.id,
            "email_address": inbox.email_address,
            "provider": inbox.provider.value,
            "status": inbox.status.value,
            "daily_send_limit": inbox.daily_send_limit
        }
        for inbox in inboxes
    ]
    
    return templates.TemplateResponse(
        "campaigns/create.html",
        {
            "request": request,
            "user": current_user,
            "settings": settings,
            "inboxes": inboxes_dict
        }
    )


@router.get("/campaigns/{campaign_id}", response_class=HTMLResponse)
async def campaign_detail_page(
    campaign_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Campaign detail/dashboard page"""
    campaign = await service.get_campaign_by_id(db, campaign_id, current_user.id)
    
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    return templates.TemplateResponse(
        "campaigns/detail.html",
        {
            "request": request,
            "user": current_user,
            "settings": settings,
            "campaign": campaign,
            "stats": {}
        }
    )


# API Endpoints

@router.post("/campaigns/api/create")
async def create_campaign(
    campaign_data: schemas.CampaignCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new warm-up campaign"""
    campaign = await service.create_campaign(
        db, 
        current_user.id, 
        campaign_data.name,
        campaign_data.description,
        campaign_data.target_daily_volume,
        campaign_data.inbox_ids,
        campaign_data.use_ai_replies,
        campaign_data.reply_rate,
        campaign_data.start_date
    )
    await db.commit()
    return {"success": True, "campaign_id": campaign.id, "message": "Campaign created successfully"}


@router.get("/campaigns/api/list")
async def list_campaigns(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all campaigns for current user"""
    campaigns = await service.get_user_campaigns(db, current_user.id)
    return {
        "campaigns": [
            {
                "id": c.id,
                "name": c.name,
                "status": c.status.value,
                "current_daily_volume": c.current_daily_volume,
                "target_daily_volume": c.target_daily_volume,
                "start_date": c.start_date.isoformat(),
                "created_at": c.created_at.isoformat()
            }
            for c in campaigns
        ]
    }


@router.get("/campaigns/api/{campaign_id}")
async def get_campaign(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get campaign details"""
    campaign = await service.get_campaign_by_id(db, campaign_id)
    
    if not campaign or campaign.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "status": campaign.status.value,
        "current_daily_volume": campaign.current_daily_volume,
        "target_daily_volume": campaign.target_daily_volume,
        "start_date": campaign.start_date.isoformat(),
        "use_ai_replies": campaign.use_ai_replies,
        "reply_rate": campaign.reply_rate
    }


@router.patch("/campaigns/api/{campaign_id}/status")
async def update_campaign_status(
    campaign_id: int,
    status_data: schemas.CampaignStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Start, pause, or stop a campaign"""
    campaign = await service.get_campaign_by_id(db, campaign_id)
    
    if not campaign or campaign.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    await service.update_campaign_status(db, campaign_id, status_data.status)
    
    return {"success": True, "message": f"Campaign {status_data.status.value}"}


@router.delete("/campaigns/api/{campaign_id}")
async def delete_campaign(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a campaign"""
    campaign = await service.get_campaign_by_id(db, campaign_id)
    
    if not campaign or campaign.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    await service.delete_campaign(db, campaign_id)
    
    return {"success": True, "message": "Campaign deleted"}


@router.get("/campaigns/api/{campaign_id}/stats")
async def get_campaign_statistics(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get campaign statistics"""
    campaign = await service.get_campaign_by_id(db, campaign_id)
    
    if not campaign or campaign.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    stats = await service.get_campaign_stats(db, campaign_id)
    
    return stats
