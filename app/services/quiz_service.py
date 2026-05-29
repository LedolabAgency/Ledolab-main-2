"""
Service layer for quiz business logic.
Processes quiz answers and creates business profiles.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def validate_quiz(quiz_data: Dict[str, str]) -> bool:
    """
    Validate quiz data structure.
    
    Args:
        quiz_data: Quiz answers dict
        
    Returns:
        True if valid
    """
    required_fields = {
        "goal",
        "current_income",
        "main_obstacle",
        "time_commitment",
        "ready_to_report",
        "paid_participation",
    }
    
    return all(field in quiz_data for field in required_fields)


def calculate_business_profile(quiz_data: Dict[str, str]) -> Dict[str, str]:
    """
    Calculate business level, focus zone, and discipline potential
    based on quiz answers.
    
    Args:
        quiz_data: Quiz answers
        
    Returns:
        Dict with business_level, focus_zone, discipline_potential
    """
    
    # ========== BUSINESS LEVEL (based on income) ==========
    income = quiz_data.get("current_income", "")
    
    if "0–500€" in income or "0-500" in income:
        business_level = "Starter"
    elif "500–1000€" in income or "500-1000" in income:
        business_level = "Builder"
    elif "1000-5000€" in income or "1000–5000€" in income:
        business_level = "Growth"
    else:
        business_level = "Scale"
    
    # ========== FOCUS ZONE (based on goal + obstacle) ==========
    goal = quiz_data.get("goal", "")
    obstacle = quiz_data.get("main_obstacle", "")
    
    # Map goals to focus zones
    if "доход" in goal.lower() or "стабильный" in goal.lower():
        focus_zone = "Sales"
    elif "трафика" in obstacle.lower() or "клиентов" in obstacle.lower():
        focus_zone = "Leads"
    elif "система" in obstacle.lower():
        focus_zone = "System"
    elif "дисциплину" in goal.lower():
        focus_zone = "Team"
    else:
        focus_zone = "Strategy"
    
    # ========== DISCIPLINE POTENTIAL (based on time + report readiness) ==========
    time_commitment = quiz_data.get("time_commitment", "")
    ready_to_report = quiz_data.get("ready_to_report", "")
    
    discipline_score = 0
    
    # Time commitment scoring
    if "3+" in time_commitment:
        discipline_score += 3
    elif "1–3" in time_commitment:
        discipline_score += 2
    else:
        discipline_score += 1
    
    # Report readiness scoring
    if "Да" in ready_to_report:
        discipline_score += 2
    elif "Не уверен" in ready_to_report:
        discipline_score += 1
    
    if discipline_score >= 4:
        discipline_potential = "High"
    elif discipline_score >= 2:
        discipline_potential = "Medium"
    else:
        discipline_potential = "Low"
    
    return {
        "business_level": business_level,
        "focus_zone": focus_zone,
        "discipline_potential": discipline_potential,
    }


def generate_profile_text(
    business_level: str,
    focus_zone: str,
    discipline_potential: str,
) -> str:
    """
    Generate human-readable business profile summary.
    
    Args:
        business_level: Starter/Builder/Growth/Scale
        focus_zone: Leads/Product/Sales/System/Team/Strategy
        discipline_potential: Low/Medium/High
        
    Returns:
        Formatted profile text
    """
    
    level_emoji = {
        "Starter": "🌱",
        "Builder": "🏗️",
        "Growth": "📈",
        "Scale": "🚀",
    }.get(business_level, "◈")
    
    discipline_emoji = {
        "Low": "🤔",
        "Medium": "⚡",
        "High": "🔥",
    }.get(discipline_potential, "◆")
    
    profile = (
        f"◈ Твой бизнес-профиль готов 🚀\n\n"
        f"{level_emoji} Уровень: {business_level}\n"
        f"🎯 Фокус роста: {focus_zone}\n"
        f"{discipline_emoji} Дисциплина: {discipline_potential}\n\n"
        f"📌 Главная зона внимания: ежедневные действия и измеримый прогресс.\n"
        f"🔜 Следующий шаг — войти в LedoLab Business Club\n\n"
        f"Там ты выстраиваешь систему роста и дисциплину:\n\n"
        f"📅 1️⃣ Ставишь одну глобальную цель на месяц\n"
        f"🧩 2️⃣ Дробишь её на этапы (по 5 дней)\n"
        f"🌅 3️⃣ Каждое утро разбиваешь задачи на мелкие шаги до 3 задач\n"
        f"🌙 4️⃣ Вечером сдаёшь отчёт\n"
        f"📊 5️⃣ Растёшь в рейтинге предпринимателей и участвуешь в борьбе за приз 🏆\n\n"
        f"📌 Суть системы:\n"
        f"Ежедневные действия → измеримый прогресс → стабильный рост 📈"
    )
    
    return profile
