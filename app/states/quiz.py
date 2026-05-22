"""
FSM states for LedoLab.
Defines state machines for quiz, goals, tasks, and reports.
"""

from aiogram.fsm.state import State, StatesGroup


class QuizStates(StatesGroup):
    """States for business quiz flow."""
    waiting_start = State()
    goal = State()
    income = State()
    obstacle = State()
    time_commitment = State()
    ready_to_report = State()
    paid_participation = State()
    completed = State()


class GoalStates(StatesGroup):
    """States for 30-day goal setup."""
    waiting_goal_text = State()
    waiting_milestones = State()
    waiting_day_text = State()
    reviewing = State()
    editing = State()
    confirmed = State()


class TaskStates(StatesGroup):
    """States for daily task management."""
    waiting_task_text = State()
    waiting_day_tasks = State()
    task_confirmed = State()
    waiting_report = State()
    report_submitted = State()


class ReportStates(StatesGroup):
    """States for daily report submission."""
    waiting_completed_count = State()
    waiting_report_text = State()
    waiting_proof = State()
    proof_submitted = State()
    completed = State()
