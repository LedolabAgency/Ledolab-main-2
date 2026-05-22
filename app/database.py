"""
Supabase database client and utilities.
"""

import logging
from typing import Optional, Dict, Any, List
from supabase import create_client, Client
from app.config import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

# Global Supabase client
supabase_client: Optional[Client] = None


def init_supabase() -> Client:
    """
    Initialize Supabase client.
    
    Returns:
        Client: Supabase client instance
    """
    global supabase_client
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("✅ Supabase connected successfully")
        return supabase_client
    except Exception as e:
        logger.error(f"❌ Supabase connection failed: {e}", exc_info=True)
        raise


def get_supabase() -> Client:
    """Get Supabase client instance."""
    global supabase_client
    if not supabase_client:
        init_supabase()
    return supabase_client


async def create_user(
    telegram_id: int,
    username: Optional[str],
    first_name: Optional[str],
    language_code: str = "ru",
) -> Dict[str, Any]:
    """
    Return lightweight onboarding user data without inserting into DB.
    
    Args:
        telegram_id: Telegram user ID
        username: Telegram username
        first_name: User's first name
        language_code: User's language preference (ru/uk)
        
    Returns:
        User data dict
    """
    try:
        existing_user = await get_user(telegram_id)
        if existing_user:
            return existing_user

        logger.info("✅ Prepared onboarding user payload: %s", telegram_id)
        return {
            "user_tg": str(telegram_id),
            "username": username,
            "first_name": first_name,
            "language_code": language_code,
        }
    except Exception as e:
        logger.error(f"Error creating user {telegram_id}: {e}", exc_info=True)
        return {}


async def get_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """
    Get user by Telegram ID from quiz_data.
    
    Args:
        telegram_id: Telegram user ID
        
    Returns:
        User data or None
    """
    try:
        sb = get_supabase()
        result = (
            sb.table("quiz_data")
            .select("*")
            .eq("user_tg", str(telegram_id))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting user {telegram_id}: {e}", exc_info=True)
        return None


async def update_user_profile(
    user_id: int,
    business_level: str,
    focus_zone: str,
    discipline_potential: str,
) -> bool:
    """
    Compatibility no-op for the simplified quiz_data schema.
    
    Args:
        user_id: User database ID
        business_level: Starter/Builder/Growth/Scale
        focus_zone: Leads/Product/Sales/System/Team/Strategy
        discipline_potential: Low/Medium/High
        
    Returns:
        True if successful
    """
    try:
        logger.info(
            "Profile calculated for user %s: level=%s focus=%s discipline=%s",
            user_id,
            business_level,
            focus_zone,
            discipline_potential,
        )
        return True
    except Exception as e:
        logger.error(f"Error updating user profile {user_id}: {e}", exc_info=True)
        return False


async def save_quiz_answers(user_id: int, quiz_data: Dict[str, str]) -> bool:
    """
    Save quiz answers to quiz_data.
    
    Args:
        user_id: User database ID
        quiz_data: Quiz answers dict
        
    Returns:
        True if successful
    """
    try:
        sb = get_supabase()
        result = (
            sb.table("quiz_data")
            .update(quiz_data)
            .eq("user_tg", str(user_id))
            .execute()
        )

        if not result.data:
            sb.table("quiz_data").insert({
                "user_tg": str(user_id),
                **quiz_data,
            }).execute()

        logger.info(f"✅ Quiz answers saved in quiz_data: {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error saving quiz answers {user_id}: {e}", exc_info=True)
        return False


async def save_phone_number(telegram_id: int, phone_number: str) -> bool:
    """Save the user's phone number into quiz_data."""
    try:
        sb = get_supabase()
        result = (
            sb.table("quiz_data")
            .update({
                "phone_number": phone_number,
            })
            .eq("user_tg", str(telegram_id))
            .execute()
        )

        if not result.data:
            sb.table("quiz_data").insert({
                "user_tg": str(telegram_id),
                "phone_number": phone_number,
            }).execute()

        logger.info("✅ Phone number saved for %s", telegram_id)
        return True
    except Exception as e:
        logger.error(f"Error saving phone number {telegram_id}: {e}", exc_info=True)
        return False


async def save_onboarding_submission(
    telegram_id: int,
    quiz_data: Dict[str, str],
    phone_number: str,
) -> bool:
    """Save the full onboarding payload into quiz_data in one write."""
    try:
        sb = get_supabase()
        payload = {
            "user_tg": str(telegram_id),
            **quiz_data,
            "phone_number": phone_number,
        }
        result = (
            sb.table("quiz_data")
            .update(payload)
            .eq("user_tg", str(telegram_id))
            .execute()
        )

        if not result.data:
            sb.table("quiz_data").insert(payload).execute()

        logger.info("✅ Full onboarding submission saved for %s", telegram_id)
        return True
    except Exception as e:
        logger.error(f"Error saving onboarding submission {telegram_id}: {e}", exc_info=True)
        return False


async def create_goal(
    user_id: int,
    goal_text: str,
    milestones: List[str],
) -> Optional[Dict[str, Any]]:
    """
    Create a 30-day business goal.
    
    Args:
        user_id: User database ID
        goal_text: Main goal text
        milestones: List of milestone steps
        
    Returns:
        Goal data or None
    """
    try:
        sb = get_supabase()
        result = sb.table("goals").insert({
            "user_id": user_id,
            "goal_text": goal_text,
            "milestones": milestones,
            "status": "active",
        }).execute()
        
        if result.data:
            logger.info(f"✅ Goal created: {user_id}")
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error creating goal {user_id}: {e}", exc_info=True)
        return None


async def get_active_goal(user_id: int) -> Optional[Dict[str, Any]]:
    """Get active goal for user."""
    try:
        sb = get_supabase()
        result = (
            sb.table("goals")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "active")
            .execute()
        )
        
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting goal {user_id}: {e}", exc_info=True)
        return None


async def create_task(
    user_id: int,
    task_text: str,
    task_date: str,
) -> Optional[Dict[str, Any]]:
    """
    Create a daily task.
    
    Args:
        user_id: User database ID
        task_text: Task description
        task_date: Date in YYYY-MM-DD format
        
    Returns:
        Task data or None
    """
    try:
        sb = get_supabase()
        result = sb.table("daily_tasks").insert({
            "user_id": user_id,
            "task_text": task_text,
            "date": task_date,
            "status": "waiting_report",
        }).execute()
        
        if result.data:
            logger.info(f"✅ Task created: {user_id} on {task_date}")
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error creating task {user_id}: {e}", exc_info=True)
        return None


async def get_today_task(user_id: int, today: str) -> Optional[Dict[str, Any]]:
    """Get today's task for user."""
    try:
        sb = get_supabase()
        result = (
            sb.table("daily_tasks")
            .select("*")
            .eq("user_id", user_id)
            .eq("date", today)
            .execute()
        )
        
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting task {user_id}: {e}", exc_info=True)
        return None


async def create_report(
    user_id: int,
    task_id: int,
    report_text: str,
    proof_type: Optional[str] = None,
    file_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Create a daily report.
    
    Args:
        user_id: User database ID
        task_id: Associated task ID
        report_text: Report content
        proof_type: Type of proof (text/video)
        file_id: Telegram file ID if applicable
        
    Returns:
        Report data or None
    """
    try:
        sb = get_supabase()
        result = sb.table("reports").insert({
            "user_id": user_id,
            "task_id": task_id,
            "report_text": report_text,
            "proof_type": proof_type,
            "file_id": file_id,
        }).execute()
        
        if result.data:
            logger.info(f"✅ Report created: {user_id}")
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error creating report {user_id}: {e}", exc_info=True)
        return None


async def award_score(
    user_id: int,
    points: int,
    reason: str,
) -> bool:
    """
    Award Leda Score to user.
    
    Args:
        user_id: User database ID
        points: Points to award (can be negative)
        reason: Reason for award
        
    Returns:
        True if successful
    """
    try:
        sb = get_supabase()
        sb.table("scores").insert({
            "user_id": user_id,
            "points": points,
            "reason": reason,
        }).execute()
        
        logger.info(f"✅ Score awarded: {user_id} +{points} ({reason})")
        return True
    except Exception as e:
        logger.error(f"Error awarding score {user_id}: {e}", exc_info=True)
        return False


async def get_user_total_score(user_id: int) -> int:
    """Get user's total Leda Score."""
    try:
        sb = get_supabase()
        result = (
            sb.table("scores")
            .select("points")
            .eq("user_id", user_id)
            .execute()
        )
        
        if result.data:
            return sum(record["points"] for record in result.data)
        return 0
    except Exception as e:
        logger.error(f"Error getting score {user_id}: {e}", exc_info=True)
        return 0


async def get_top_users(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get top users by Leda Score for rating.
    
    Args:
        limit: Number of users to return
        
    Returns:
        List of users with their scores
    """
    try:
        sb = get_supabase()
        # This requires aggregation on backend or we fetch and sort
        result = sb.table("users").select("id,username,first_name").execute()
        
        if result.data:
            users_with_scores = []
            for user in result.data:
                total_score = await get_user_total_score(user["id"])
                users_with_scores.append({
                    **user,
                    "total_score": total_score,
                })
            
            # Sort by score descending
            users_with_scores.sort(key=lambda x: x["total_score"], reverse=True)
            return users_with_scores[:limit]
        
        return []
    except Exception as e:
        logger.error(f"Error getting top users: {e}", exc_info=True)
        return []
