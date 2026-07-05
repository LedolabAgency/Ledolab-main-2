"""
Supabase database client and utilities.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from supabase import create_client, Client
from app.config import SUPABASE_URL, SUPABASE_KEY
from app import cache

logger = logging.getLogger(__name__)

# Global Supabase client
supabase_client: Optional[Client] = None


def _quiz_done_cache_key(telegram_id: int) -> str:
    return f"quiz_done:{telegram_id}"


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


async def get_club_user(telegram_id: int) -> Optional[Dict[str, Any]]:
    """Get a club user record from the main users table."""
    try:
        sb = get_supabase()
        result = (
            sb.table("users")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting club user {telegram_id}: {e}", exc_info=True)
        return None


async def get_club_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Get a club user record by internal users.id."""
    try:
        sb = get_supabase()
        result = (
            sb.table("users")
            .select("*")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting club user by id {user_id}: {e}", exc_info=True)
        return None


async def ensure_club_user(
    telegram_id: int,
    username: Optional[str],
    first_name: Optional[str],
    language_code: str = "ru",
    phone_number: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Ensure the main users table contains the participant."""
    try:
        existing = await get_club_user(telegram_id)
        if existing:
            update_payload: Dict[str, Any] = {}
            if phone_number and not existing.get("phone_number"):
                update_payload["phone_number"] = phone_number
            if username and not existing.get("username"):
                update_payload["username"] = username
            if first_name and not existing.get("first_name"):
                update_payload["first_name"] = first_name
            if update_payload:
                sb = get_supabase()
                result = (
                    sb.table("users")
                    .update(update_payload)
                    .eq("telegram_id", telegram_id)
                    .execute()
                )
                if result.data:
                    return result.data[0]
            return existing

        quiz_profile = await get_user(telegram_id)
        sb = get_supabase()
        payload = {
            "telegram_id": telegram_id,
            "username": username or (quiz_profile or {}).get("username"),
            "first_name": first_name or (quiz_profile or {}).get("first_name"),
            "phone_number": phone_number or (quiz_profile or {}).get("phone_number"),
            "language_code": language_code,
            "business_level": (quiz_profile or {}).get("current_income"),
        }
        result = sb.table("users").insert(payload).execute()
        if result.data:
            logger.info("✅ Club user ensured: %s", telegram_id)
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error ensuring club user {telegram_id}: {e}", exc_info=True)
        return None


async def resolve_telegram_id_by_handle_or_id(raw_value: str) -> Optional[int]:
    """Resolve a target telegram id from plain id or @username."""
    candidate = raw_value.strip()
    if not candidate:
        return None

    if candidate.isdigit():
        return int(candidate)

    username = candidate.lstrip("@")
    try:
        sb = get_supabase()

        users_result = (
            sb.table("users")
            .select("telegram_id")
            .eq("username", username)
            .limit(1)
            .execute()
        )
        if users_result.data:
            return int(users_result.data[0]["telegram_id"])

        quiz_result = (
            sb.table("quiz_data")
            .select("user_tg")
            .eq("username", username)
            .limit(1)
            .execute()
        )
        if quiz_result.data:
            return int(quiz_result.data[0]["user_tg"])
    except Exception as e:
        logger.error(f"Error resolving target {raw_value}: {e}", exc_info=True)
    return None


async def has_completed_quiz(telegram_id: int) -> bool:
    """Check whether the user has completed onboarding in quiz_data."""
    try:
        cached = await cache.get_data(_quiz_done_cache_key(telegram_id))
        if cached is not None:
            return cached == "1"

        quiz_profile = await get_user(telegram_id)
        if not quiz_profile:
            await cache.set_data(_quiz_done_cache_key(telegram_id), "0", ex=300)
            return False

        required_fields = [
            "goal",
            "current_income",
            "main_obstacle",
            "time_commitment",
            "ready_to_report",
            "paid_participation",
            "phone_number",
        ]
        is_completed = all(bool(quiz_profile.get(field)) for field in required_fields)
        await cache.set_data(_quiz_done_cache_key(telegram_id), "1" if is_completed else "0", ex=300)
        return is_completed
    except Exception as e:
        logger.error(f"Error checking quiz completion for {telegram_id}: {e}", exc_info=True)
        return False


async def has_phone_number(telegram_id: int) -> bool:
    """Check whether quiz_data already contains a phone number for the user."""
    try:
        quiz_profile = await get_user(telegram_id)
        return bool((quiz_profile or {}).get("phone_number"))
    except Exception as e:
        logger.error(f"Error checking phone number for {telegram_id}: {e}", exc_info=True)
        return False


async def has_any_day_tasks(user_id: str) -> bool:
    """Check whether the user has ever created at least one day task."""
    try:
        sb = get_supabase()
        result = (
            sb.table("daily_tasks")
            .select("id")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.error(f"Error checking day tasks for {user_id}: {e}", exc_info=True)
        return False


async def reset_user_data(telegram_id: int) -> Dict[str, int]:
    """Delete all database rows for a user across quiz and club tables."""
    stats = {
        "quiz_data": 0,
        "referrals": 0,
        "daily_report_votes": 0,
        "daily_reports": 0,
        "reports": 0,
        "daily_tasks": 0,
        "daily_statuses": 0,
        "scores": 0,
        "goals": 0,
        "users": 0,
    }
    try:
        sb = get_supabase()

        club_user = await get_club_user(telegram_id)
        club_user_id = (club_user or {}).get("id")

        if club_user_id:
            goal_rows = (
                sb.table("goals")
                .select("id")
                .eq("user_id", club_user_id)
                .execute()
            ).data or []
            goal_ids = [row["id"] for row in goal_rows if row.get("id")]

            task_rows = (
                sb.table("daily_tasks")
                .select("id")
                .eq("user_id", club_user_id)
                .execute()
            ).data or []
            task_ids = [row["id"] for row in task_rows if row.get("id")]

            report_rows = (
                sb.table("reports")
                .select("id")
                .eq("user_id", club_user_id)
                .execute()
            ).data or []
            report_ids = [row["id"] for row in report_rows if row.get("id")]

            daily_report_rows = (
                sb.table("daily_reports")
                .select("id")
                .eq("user_id", club_user_id)
                .execute()
            ).data or []
            daily_report_ids = [row["id"] for row in daily_report_rows if row.get("id")]

            for report_id in daily_report_ids:
                vote_result = (
                    sb.table("daily_report_votes")
                    .delete()
                    .eq("report_id", report_id)
                    .execute()
                )
                stats["daily_report_votes"] += len(vote_result.data or [])

            for report_id in report_ids:
                report_delete = (
                    sb.table("reports")
                    .delete()
                    .eq("id", report_id)
                    .execute()
                )
                stats["reports"] += len(report_delete.data or [])

            for report_id in daily_report_ids:
                daily_report_delete = (
                    sb.table("daily_reports")
                    .delete()
                    .eq("id", report_id)
                    .execute()
                )
                stats["daily_reports"] += len(daily_report_delete.data or [])

            for task_id in task_ids:
                task_delete = (
                    sb.table("daily_tasks")
                    .delete()
                    .eq("id", task_id)
                    .execute()
                )
                stats["daily_tasks"] += len(task_delete.data or [])

            daily_status_delete = (
                sb.table("daily_statuses")
                .delete()
                .eq("user_id", club_user_id)
                .execute()
            )
            stats["daily_statuses"] = len(daily_status_delete.data or [])

            scores_delete = (
                sb.table("scores")
                .delete()
                .eq("user_id", club_user_id)
                .execute()
            )
            stats["scores"] = len(scores_delete.data or [])

            for goal_id in goal_ids:
                goal_delete = (
                    sb.table("goals")
                    .delete()
                    .eq("id", goal_id)
                    .execute()
                )
                stats["goals"] += len(goal_delete.data or [])

        quiz_result = (
            sb.table("quiz_data")
            .delete()
            .eq("user_tg", str(telegram_id))
            .execute()
        )
        stats["quiz_data"] = len(quiz_result.data or [])

        referrals_as_referred = (
            sb.table("referrals")
            .delete()
            .eq("referred_telegram_id", telegram_id)
            .execute()
        )
        stats["referrals"] += len(referrals_as_referred.data or [])

        referrals_as_referrer = (
            sb.table("referrals")
            .delete()
            .eq("referrer_telegram_id", telegram_id)
            .execute()
        )
        stats["referrals"] += len(referrals_as_referrer.data or [])

        users_result = (
            sb.table("users")
            .delete()
            .eq("telegram_id", telegram_id)
            .execute()
        )
        stats["users"] = len(users_result.data or [])
        await cache.delete_data(_quiz_done_cache_key(telegram_id))
        logger.info("Full DB reset completed for %s | stats=%s", telegram_id, stats)
    except Exception as e:
        logger.error(f"Error resetting database data for {telegram_id}: {e}", exc_info=True)
    return stats


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
            logger.info(
                "No existing quiz_data row for %s yet. Deferring insert until phone number is shared.",
                user_id,
            )
            await cache.delete_data(_quiz_done_cache_key(user_id))
            return True

        await cache.delete_data(_quiz_done_cache_key(user_id))
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

        await cache.delete_data(_quiz_done_cache_key(telegram_id))
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

        await ensure_club_user(
            telegram_id=telegram_id,
            username=None,
            first_name=None,
            phone_number=phone_number,
        )

        await cache.delete_data(_quiz_done_cache_key(telegram_id))
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


async def set_active_goal(
    user_id: str,
    goal_text: str,
    milestones: List[str],
) -> Optional[Dict[str, Any]]:
    """Archive previous goals and create a new active one."""
    try:
        sb = get_supabase()
        sb.table("goals").update({"status": "archived"}).eq("user_id", user_id).eq("status", "active").execute()
        return await create_goal(user_id, goal_text, milestones)
    except Exception as e:
        logger.error(f"Error setting active goal {user_id}: {e}", exc_info=True)
        return None


async def update_active_goal_milestones(
    user_id: str,
    milestones: List[str],
) -> Optional[Dict[str, Any]]:
    """Replace the 5-day route for the current active 30-day goal."""
    try:
        sb = get_supabase()
        result = (
            sb.table("goals")
            .update({"milestones": milestones})
            .eq("user_id", user_id)
            .eq("status", "active")
            .execute()
        )
        if result.data:
            logger.info("✅ Active goal route updated: %s", user_id)
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error updating active goal route {user_id}: {e}", exc_info=True)
        return None


async def get_week_plan_for_user(user_id: str) -> List[str]:
    """Return the current 5-day plan for the active goal."""
    goal = await get_active_goal(user_id)
    if not goal:
        return []
    return goal.get("milestones") or []


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
    task_type: str = "main",
    goal_id: Optional[str] = None,
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
        existing = (
            sb.table("daily_tasks")
            .select("*")
            .eq("user_id", user_id)
            .eq("date", task_date)
            .eq("task_type", task_type)
            .limit(1)
            .execute()
        )

        payload = {
            "user_id": user_id,
            "goal_id": goal_id,
            "task_text": task_text,
            "task_type": task_type,
            "date": task_date,
            "status": "waiting_report",
        }

        if existing.data:
            result = (
                sb.table("daily_tasks")
                .update(payload)
                .eq("id", existing.data[0]["id"])
                .execute()
            )
        else:
            result = sb.table("daily_tasks").insert(payload).execute()
        
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
            .order("created_at", desc=False)
            .execute()
        )
        
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting task {user_id}: {e}", exc_info=True)
        return None


async def get_today_tasks(user_id: str, today: str) -> List[Dict[str, Any]]:
    """Get all daily tasks for the current day."""
    try:
        sb = get_supabase()
        result = (
            sb.table("daily_tasks")
            .select("*")
            .eq("user_id", user_id)
            .eq("date", today)
            .in_("task_type", ["day_1", "day_2", "day_3"])
            .order("task_type", desc=False)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Error getting today tasks {user_id}: {e}", exc_info=True)
        return []


async def get_oldest_open_task_date(user_id: str) -> Optional[str]:
    """Earliest date that has day tasks but no report row at all.

    Used to enforce "one open day at a time": a user must close the previous
    day with a report before a new day can be started. Days already acted upon
    by an admin (approved / rejected / redo_requested) are not considered open —
    they carry their own flow and must not block progression.
    """
    try:
        sb = get_supabase()
        task_rows = (
            sb.table("daily_tasks")
            .select("date")
            .eq("user_id", user_id)
            .in_("task_type", ["day_1", "day_2", "day_3"])
            .execute()
        ).data or []
        task_dates = sorted({r["date"] for r in task_rows if r.get("date")})
        if not task_dates:
            return None
        report_rows = (
            sb.table("daily_reports")
            .select("report_date")
            .eq("user_id", user_id)
            .execute()
        ).data or []
        reported_dates = {r["report_date"] for r in report_rows if r.get("report_date")}
        for d in task_dates:
            if d not in reported_dates:
                return d
        return None
    except Exception as e:
        logger.error("Error getting oldest open task date %s: %s", user_id, e, exc_info=True)
        return None


async def get_task_by_type(user_id: str, today: str, task_type: str = "main") -> Optional[Dict[str, Any]]:
    """Get today's task by task type."""
    try:
        sb = get_supabase()
        result = (
            sb.table("daily_tasks")
            .select("*")
            .eq("user_id", user_id)
            .eq("date", today)
            .eq("task_type", task_type)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error getting task by type {user_id}: {e}", exc_info=True)
        return None


async def update_task_status(task_id: str, status: str) -> bool:
    """Update the task status."""
    try:
        sb = get_supabase()
        sb.table("daily_tasks").update({"status": status}).eq("id", task_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error updating task status {task_id}: {e}", exc_info=True)
        return False


async def update_tasks_status(task_ids: List[str], status: str) -> bool:
    """Update a batch of task statuses."""
    try:
        if not task_ids:
            return True
        sb = get_supabase()
        sb.table("daily_tasks").update({"status": status}).in_("id", task_ids).execute()
        return True
    except Exception as e:
        logger.error(f"Error updating task batch status {task_ids}: {e}", exc_info=True)
        return False


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
        normalized_file_id = str(file_id or "").strip()
        if normalized_file_id:
            sb = get_supabase()
            duplicate_check = (
                sb.table("reports")
                .select("id")
                .eq("user_id", user_id)
                .eq("file_id", normalized_file_id)
                .limit(1)
                .execute()
            )
            if duplicate_check.data:
                logger.warning(
                    "Rejected duplicate report proof: user_id=%s task_id=%s file_id=%s",
                    user_id,
                    task_id,
                    normalized_file_id,
                )
                return None

        sb = get_supabase()
        result = sb.table("reports").insert({
            "user_id": user_id,
            "task_id": task_id,
            "report_text": report_text,
            "proof_type": proof_type,
            "file_id": normalized_file_id or None,
        }).execute()
        
        if result.data:
            logger.info(f"✅ Report created: {user_id}")
            await update_task_status(task_id, "reported")
            return result.data[0]
        return None
    except Exception as e:
        logger.error(f"Error creating report {user_id}: {e}", exc_info=True)
        return None


async def has_report_file_for_user(user_id: str, file_id: str) -> bool:
    """Check whether a proof file was already used by this user."""
    try:
        normalized_user_id = str(user_id).strip()
        normalized_file_id = str(file_id or "").strip()
        if not normalized_user_id or not normalized_file_id:
            return False

        sb = get_supabase()
        result = (
            sb.table("reports")
            .select("id")
            .eq("user_id", normalized_user_id)
            .eq("file_id", normalized_file_id)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.error(
            "Error checking report file usage for user %s: %s",
            user_id,
            e,
            exc_info=True,
        )
        return False


async def get_daily_report(user_id: str, report_date: str) -> Optional[Dict[str, Any]]:
    """Fetch the daily report record for a user and date."""
    try:
        sb = get_supabase()
        result = (
            sb.table("daily_reports")
            .select("*")
            .eq("user_id", user_id)
            .eq("report_date", report_date)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Error getting daily report {user_id} {report_date}: {e}", exc_info=True)
        return None


async def get_daily_report_by_id(report_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a daily report by id."""
    try:
        sb = get_supabase()
        result = sb.table("daily_reports").select("*").eq("id", report_id).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Error getting daily report by id {report_id}: {e}", exc_info=True)
        return None


async def get_daily_report_by_group_message(chat_id: int, message_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a daily report by its Telegram group summary message."""
    try:
        sb = get_supabase()
        result = (
            sb.table("daily_reports")
            .select("*")
            .eq("group_chat_id", chat_id)
            .eq("group_message_id", message_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Error getting daily report by group message {chat_id}:{message_id}: {e}", exc_info=True)
        return None


async def create_or_update_daily_report(
    user_id: str,
    report_date: str,
    tasks_snapshot: List[str],
    report_payload: List[Dict[str, Any]],
    summary_text: str,
    score_awarded: int,
    status: str = "approved",
) -> Optional[Dict[str, Any]]:
    """Create or update a single daily report summary for the user."""
    try:
        sb = get_supabase()
        payload = {
            "user_id": user_id,
            "report_date": report_date,
            "tasks_snapshot": tasks_snapshot,
            "report_payload": report_payload,
            "summary_text": summary_text,
            "status": status,
            "score_awarded": score_awarded,
            "flags": 0,
            "group_message_id": None,
            "group_chat_id": None,
            "admin_comment": None,
        }
        existing = await get_daily_report(user_id, report_date)
        if existing:
            sb.table("daily_report_votes").delete().eq("report_id", existing["id"]).execute()
            result = (
                sb.table("daily_reports")
                .update(payload)
                .eq("id", existing["id"])
                .execute()
            )
        else:
            result = sb.table("daily_reports").insert(payload).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Error creating/updating daily report {user_id} {report_date}: {e}", exc_info=True)
        return None


async def set_daily_report_group_post(report_id: str, chat_id: int, message_id: int) -> bool:
    """Save the Telegram group message reference for a daily report."""
    try:
        sb = get_supabase()
        sb.table("daily_reports").update({
            "group_chat_id": chat_id,
            "group_message_id": message_id,
        }).eq("id", report_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error saving report group post {report_id}: {e}", exc_info=True)
        return False


async def delete_daily_report(report_id: str) -> bool:
    """Delete a daily report and its votes."""
    try:
        sb = get_supabase()
        sb.table("daily_report_votes").delete().eq("report_id", report_id).execute()
        sb.table("daily_reports").delete().eq("id", report_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error deleting daily report {report_id}: {e}", exc_info=True)
        return False


async def add_daily_report_vote(report_id: str, voter_telegram_id: int, vote_type: str) -> bool:
    """Record a single unique vote for a daily report."""
    try:
        sb = get_supabase()
        existing = (
            sb.table("daily_report_votes")
            .select("id")
            .eq("report_id", report_id)
            .eq("voter_telegram_id", voter_telegram_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            return False
        sb.table("daily_report_votes").insert({
            "report_id": report_id,
            "voter_telegram_id": voter_telegram_id,
            "vote_type": vote_type,
        }).execute()
        return True
    except Exception as e:
        logger.error(f"Error adding daily report vote {report_id}: {e}", exc_info=True)
        return False


async def count_daily_report_votes(report_id: str, vote_type: str) -> int:
    """Count votes of a given type for a report."""
    try:
        sb = get_supabase()
        result = (
            sb.table("daily_report_votes")
            .select("id")
            .eq("report_id", report_id)
            .eq("vote_type", vote_type)
            .execute()
        )
        return len(result.data or [])
    except Exception as e:
        logger.error(f"Error counting report votes {report_id}: {e}", exc_info=True)
        return 0


async def update_daily_report_flags(report_id: str, flags: int) -> bool:
    """Update flags counter for a daily report."""
    try:
        sb = get_supabase()
        sb.table("daily_reports").update({"flags": flags}).eq("id", report_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error updating report flags {report_id}: {e}", exc_info=True)
        return False


async def set_daily_report_status(report_id: str, status: str, admin_comment: Optional[str] = None) -> bool:
    """Update report status and optional admin comment."""
    try:
        payload: Dict[str, Any] = {
            "status": status,
            "reviewed_at": datetime.utcnow().isoformat(),
        }
        if admin_comment is not None:
            payload["admin_comment"] = admin_comment
        sb = get_supabase()
        sb.table("daily_reports").update(payload).eq("id", report_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error setting daily report status {report_id}: {e}", exc_info=True)
        return False


async def update_daily_report_summary_text(report_id: str, summary_text: str) -> bool:
    """Update summary text after admin decision if needed."""
    try:
        sb = get_supabase()
        sb.table("daily_reports").update({"summary_text": summary_text}).eq("id", report_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error updating report summary {report_id}: {e}", exc_info=True)
        return False


async def upsert_referral_link(referrer_telegram_id: int, referred_telegram_id: int) -> Optional[Dict[str, Any]]:
    """Create a pending referral relation or return the existing one."""
    try:
        if referrer_telegram_id == referred_telegram_id:
            return None
        sb = get_supabase()
        existing = (
            sb.table("referrals")
            .select("*")
            .eq("referred_telegram_id", referred_telegram_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            return existing.data[0]

        referrer_row = await get_club_user(referrer_telegram_id)
        referred_row = await get_club_user(referred_telegram_id)
        payload = {
            "referrer_telegram_id": referrer_telegram_id,
            "referred_telegram_id": referred_telegram_id,
            "referrer_user_id": (referrer_row or {}).get("id"),
            "referred_user_id": (referred_row or {}).get("id"),
        }
        result = sb.table("referrals").insert(payload).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(
            f"Error upserting referral link referrer={referrer_telegram_id} referred={referred_telegram_id}: {e}",
            exc_info=True,
        )
        return None


async def get_referral_by_referred_telegram(referred_telegram_id: int) -> Optional[Dict[str, Any]]:
    try:
        sb = get_supabase()
        result = (
            sb.table("referrals")
            .select("*")
            .eq("referred_telegram_id", referred_telegram_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Error getting referral by referred telegram {referred_telegram_id}: {e}", exc_info=True)
        return None


async def get_referral_by_referred_user(user_id: str) -> Optional[Dict[str, Any]]:
    try:
        sb = get_supabase()
        result = (
            sb.table("referrals")
            .select("*")
            .eq("referred_user_id", user_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Error getting referral by referred user {user_id}: {e}", exc_info=True)
        return None


async def sync_referral_users(referred_telegram_id: int) -> Optional[Dict[str, Any]]:
    """Hydrate referral row with current users.id values after onboarding."""
    try:
        referral = await get_referral_by_referred_telegram(referred_telegram_id)
        if not referral:
            return None

        referred_row = await get_club_user(referred_telegram_id)
        referrer_row = await get_club_user(int(referral["referrer_telegram_id"]))
        payload = {
            "referred_user_id": (referred_row or {}).get("id"),
            "referrer_user_id": (referrer_row or {}).get("id"),
        }
        sb = get_supabase()
        result = sb.table("referrals").update(payload).eq("id", referral["id"]).execute()
        return result.data[0] if result.data else {**referral, **payload}
    except Exception as e:
        logger.error(f"Error syncing referral users for {referred_telegram_id}: {e}", exc_info=True)
        return None


async def count_daily_reports_for_user(user_id: str) -> int:
    try:
        sb = get_supabase()
        result = (
            sb.table("daily_reports")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        return len(result.data or [])
    except Exception as e:
        logger.error(f"Error counting daily reports for {user_id}: {e}", exc_info=True)
        return 0


async def update_referral_progress(referral_id: str, reports_completed: int) -> bool:
    try:
        sb = get_supabase()
        sb.table("referrals").update({"reports_completed": reports_completed}).eq("id", referral_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error updating referral progress {referral_id}: {e}", exc_info=True)
        return False


async def mark_referral_bonus_awarded(referral_id: str, reports_completed: int) -> bool:
    try:
        sb = get_supabase()
        sb.table("referrals").update({
            "bonus_awarded": True,
            "reports_completed": reports_completed,
            "awarded_at": datetime.utcnow().isoformat(),
        }).eq("id", referral_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error marking referral award {referral_id}: {e}", exc_info=True)
        return False


async def increment_user_warnings(user_id: str, amount: int = 1) -> Optional[Dict[str, Any]]:
    """Increase warnings counter and auto-ban at 3 or more warnings."""
    try:
        sb = get_supabase()
        result = sb.table("users").select("id,warnings_count,is_banned").eq("id", user_id).limit(1).execute()
        if not result.data:
            return None
        current = result.data[0]
        warnings_count = int(current.get("warnings_count") or 0) + amount
        payload = {
            "warnings_count": warnings_count,
            "is_banned": warnings_count >= 3,
        }
        updated = sb.table("users").update(payload).eq("id", user_id).execute()
        return updated.data[0] if updated.data else {**current, **payload}
    except Exception as e:
        logger.error(f"Error incrementing warnings {user_id}: {e}", exc_info=True)
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
        result = sb.table("users").select("id,telegram_id,username,first_name,warnings_count").execute()
        
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


async def get_user_score_for_period(user_id: str, start_iso: str, end_iso: str) -> int:
    """Sum a single user's score points within [start_iso, end_iso)."""
    try:
        sb = get_supabase()
        rows = (
            sb.table("scores")
            .select("points,created_at")
            .eq("user_id", user_id)
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            .execute()
        ).data or []
        return sum(int(r.get("points") or 0) for r in rows)
    except Exception as e:
        logger.error("Error getting period score for %s: %s", user_id, e, exc_info=True)
        return 0


async def get_top_users_for_period(start_iso: str, end_iso: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Aggregate scores for a specific period and return ranked users."""
    try:
        sb = get_supabase()
        users_rows = (
            sb.table("users")
            .select("id,telegram_id,username,first_name,warnings_count")
            .execute()
        ).data or []
        scores_rows = (
            sb.table("scores")
            .select("user_id,points,created_at")
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            .execute()
        ).data or []

        totals: Dict[str, int] = {}
        for row in scores_rows:
            user_id = row.get("user_id")
            if not user_id:
                continue
            totals[str(user_id)] = totals.get(str(user_id), 0) + int(row.get("points") or 0)

        users_with_scores: List[Dict[str, Any]] = []
        for user in users_rows:
            total_score = totals.get(str(user["id"]), 0)
            if total_score <= 0:
                continue
            users_with_scores.append({**user, "total_score": total_score})

        users_with_scores.sort(key=lambda item: int(item.get("total_score", 0)), reverse=True)
        return users_with_scores[:limit]
    except Exception as e:
        logger.error(f"Error getting period top users {start_iso}..{end_iso}: {e}", exc_info=True)
        return []


async def get_admin_analytics(today: str) -> Dict[str, int]:
    """Return high-level admin analytics for the club."""
    try:
        sb = get_supabase()

        quiz_rows = (
            sb.table("quiz_data")
            .select("user_tg,phone_number,goal,current_income,main_obstacle,time_commitment,ready_to_report,paid_participation")
            .execute()
        ).data or []
        users_rows = sb.table("users").select("id,is_banned").execute().data or []
        goal_rows = sb.table("goals").select("id,user_id,status").execute().data or []
        all_task_rows = sb.table("daily_tasks").select("user_id,date").execute().data or []
        today_task_rows = [row for row in all_task_rows if str(row.get("date") or "") == today]
        all_report_rows = sb.table("daily_reports").select("id,user_id,report_date").execute().data or []
        today_report_rows = [row for row in all_report_rows if str(row.get("report_date") or "") == today]
        referral_rows = sb.table("referrals").select("id,bonus_awarded").execute().data or []

        required_fields = [
            "goal",
            "current_income",
            "main_obstacle",
            "time_commitment",
            "ready_to_report",
            "paid_participation",
            "phone_number",
        ]
        completed_quiz = sum(1 for row in quiz_rows if all(bool(row.get(field)) for field in required_fields))
        with_phone = sum(1 for row in quiz_rows if bool(row.get("phone_number")))
        users_with_any_goal = {str(row.get("user_id")) for row in goal_rows if row.get("user_id")}
        users_with_any_day = {str(row.get("user_id")) for row in all_task_rows if row.get("user_id")}
        planned_today = {str(row.get("user_id")) for row in today_task_rows if row.get("user_id")}
        reported_today = {str(row.get("user_id")) for row in today_report_rows if row.get("user_id")}
        banned_users = sum(1 for row in users_rows if bool(row.get("is_banned")))

        return {
            "completed_quiz": completed_quiz,
            "with_phone": with_phone,
            "club_users": len(users_rows),
            "users_with_goal": len(users_with_any_goal),
            "active_goals": sum(1 for row in goal_rows if row.get("status") == "active"),
            "users_with_day_tasks": len(users_with_any_day),
            "planned_today": len(planned_today),
            "reported_today": len(reported_today),
            "missing_reports_today": max(len(planned_today) - len(reported_today), 0),
            "reports_total": len(all_report_rows),
            "referrals_total": len(referral_rows),
            "referrals_awarded": sum(1 for row in referral_rows if bool(row.get("bonus_awarded"))),
            "banned_users": banned_users,
        }
    except Exception as e:
        logger.error(f"Error getting admin analytics for {today}: {e}", exc_info=True)
        return {
            "completed_quiz": 0,
            "with_phone": 0,
            "club_users": 0,
            "users_with_goal": 0,
            "active_goals": 0,
            "users_with_day_tasks": 0,
            "planned_today": 0,
            "reported_today": 0,
            "missing_reports_today": 0,
            "reports_total": 0,
            "referrals_total": 0,
            "referrals_awarded": 0,
            "banned_users": 0,
        }


async def get_users_with_today_tasks(today: str) -> List[Dict[str, Any]]:
    """Return active club users together with their task texts for today."""
    try:
        sb = get_supabase()
        task_rows = (
            sb.table("daily_tasks")
            .select("user_id,task_text,task_type")
            .eq("date", today)
            .in_("task_type", ["day_1", "day_2", "day_3"])
            .execute()
        ).data or []
        if not task_rows:
            return []
        user_tasks: dict[str, list[str]] = {}
        for row in task_rows:
            uid = row["user_id"]
            if uid not in user_tasks:
                user_tasks[uid] = []
            if row.get("task_text"):
                user_tasks[uid].append(row["task_text"])
        user_ids = list(user_tasks.keys())
        users = (
            sb.table("users")
            .select("id,telegram_id,username,first_name,is_banned")
            .in_("id", user_ids)
            .execute()
        ).data or []
        return [
            {**u, "tasks": user_tasks.get(u["id"], [])}
            for u in users
            if not u.get("is_banned")
        ]
    except Exception as e:
        logger.error("Error in get_users_with_today_tasks %s: %s", today, e, exc_info=True)
        return []


async def get_users_with_tasks_no_report(today: str) -> List[Dict[str, Any]]:
    """Return users who have tasks today but haven't submitted a report yet."""
    try:
        sb = get_supabase()
        task_rows = (
            sb.table("daily_tasks")
            .select("user_id,task_text,task_type")
            .eq("date", today)
            .in_("task_type", ["day_1", "day_2", "day_3"])
            .execute()
        ).data or []
        if not task_rows:
            return []
        user_tasks: dict[str, list[str]] = {}
        for row in task_rows:
            uid = row["user_id"]
            if uid not in user_tasks:
                user_tasks[uid] = []
            if row.get("task_text"):
                user_tasks[uid].append(row["task_text"])
        report_rows = (
            sb.table("daily_reports")
            .select("user_id")
            .eq("report_date", today)
            .execute()
        ).data or []
        reported_ids = {row["user_id"] for row in report_rows}
        need_reminder = [uid for uid in user_tasks if uid not in reported_ids]
        if not need_reminder:
            return []
        users = (
            sb.table("users")
            .select("id,telegram_id,username,first_name,is_banned")
            .in_("id", need_reminder)
            .execute()
        ).data or []
        return [
            {**u, "tasks": user_tasks.get(u["id"], [])}
            for u in users
            if not u.get("is_banned")
        ]
    except Exception as e:
        logger.error("Error in get_users_with_tasks_no_report %s: %s", today, e, exc_info=True)
        return []


async def get_users_with_report_yesterday_no_tasks_today(
    yesterday: str, today: str
) -> List[Dict[str, Any]]:
    """Return users who submitted a report for yesterday but haven't set tasks for today yet."""
    try:
        sb = get_supabase()
        report_rows = (
            sb.table("daily_reports")
            .select("user_id,status")
            .eq("report_date", yesterday)
            .execute()
        ).data or []
        reported_ids = list({
            r["user_id"] for r in report_rows
            if str(r.get("status") or "").lower() not in {"redo_requested", "rejected"}
        })
        if not reported_ids:
            return []

        task_rows = (
            sb.table("daily_tasks")
            .select("user_id")
            .eq("date", today)
            .execute()
        ).data or []
        users_with_tasks = {r["user_id"] for r in task_rows}

        need_reminder = [uid for uid in reported_ids if uid not in users_with_tasks]
        if not need_reminder:
            return []

        users = (
            sb.table("users")
            .select("id,telegram_id,username,first_name,is_banned")
            .in_("id", need_reminder)
            .execute()
        ).data or []

        goal_rows = (
            sb.table("goals")
            .select("user_id,milestones")
            .in_("user_id", need_reminder)
            .eq("status", "active")
            .execute()
        ).data or []
        goal_by_user = {g["user_id"]: g.get("milestones") or [] for g in goal_rows}

        return [
            {**u, "milestones": goal_by_user.get(u["id"], [])}
            for u in users
            if not u.get("is_banned")
        ]
    except Exception as e:
        logger.error(
            "Error in get_users_with_report_yesterday_no_tasks_today %s/%s: %s",
            yesterday, today, e, exc_info=True,
        )
        return []


async def mark_daily_status(user_id: str, status_date: str, status: str) -> bool:
    """Persist a neutral or failed day marker."""
    try:
        sb = get_supabase()
        existing = (
            sb.table("daily_statuses")
            .select("*")
            .eq("user_id", user_id)
            .eq("status_date", status_date)
            .limit(1)
            .execute()
        )
        payload = {
            "user_id": user_id,
            "status_date": status_date,
            "status": status,
        }
        if existing.data:
            sb.table("daily_statuses").update(payload).eq("id", existing.data[0]["id"]).execute()
        else:
            sb.table("daily_statuses").insert(payload).execute()
        return True
    except Exception as e:
        logger.error(f"Error marking daily status for {user_id}: {e}", exc_info=True)
        return False
