"""
Service layer for daily report submission and scoring.
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime
from app import database, cache, config

logger = logging.getLogger(__name__)


async def submit_report(
    user_id: str,
    task_id: str,
    report_text: str,
    completed_tasks: int = 0,
    proof_type: Optional[str] = None,
    file_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Submit daily report and calculate score.
    
    Args:
        user_id: User database ID
        task_id: Associated task ID
        report_text: Report content
        proof_type: Type of proof (text/video)
        file_id: Telegram file ID if applicable
        
    Returns:
        Report data with awarded score
    """
    try:
        # Create report
        report = await database.create_report(
            user_id=user_id,
            task_id=task_id,
            report_text=report_text,
            proof_type=proof_type,
            file_id=file_id,
        )
        
        if not report:
            return None
        
        total_score = max(0, completed_tasks) * 10
        if completed_tasks >= 3:
            total_score += 10
        if proof_type == "video":
            reason = f"Daily report submitted with proof ({completed_tasks}/3)"
        else:
            reason = f"Daily report submitted ({completed_tasks}/3)"
        
        # Award score
        await database.award_score(user_id, total_score, reason)
        
        logger.info(f"✅ Report submitted: {user_id} +{total_score}")
        
        return {
            **report,
            "score_awarded": total_score,
            "completed_tasks": completed_tasks,
        }
    except Exception as e:
        logger.error(f"Error submitting report {user_id}: {e}", exc_info=True)
        return None


async def report_summary_text(
    username: Optional[str],
    task_text: str,
    report_text: str,
    score: int,
) -> str:
    """
    Generate public report text for group.
    
    Args:
        username: Telegram username
        task_text: Original task
        report_text: Report content
        score: Score awarded
        
    Returns:
        Formatted report text
    """
    user_mention = f"@{username}" if username else "Участник"
    
    return (
        f"🔥 Отчет предпринимателя\n\n"
        f"👤 Участник: {user_mention}\n\n"
        f"🎯 Задача дня:\n"
        f"{task_text}\n\n"
        f"✅ Результат:\n"
        f"{report_text}\n\n"
        f"⚡ +{score} Business Score\n\n"
        f"Движение зафиксировано."
    )
