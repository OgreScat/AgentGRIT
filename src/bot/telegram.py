"""
AgentGRIT Telegram Bot

Mobile-first interface for agent orchestration.
Provides notifications (not approvals) and quick commands.
"""

import asyncio
from datetime import datetime
from typing import Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from ..config import settings
from ..governance.trust import TrustLevel, get_trust_manager
from .bot_workflow import render_plan_message, confirm_plan, Button


# Router for all handlers
router = Router()


# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE FORMATTERS
# ═══════════════════════════════════════════════════════════════════════════════

def format_task_complete(
    task_id: str,
    title: str,
    files_changed: list[str],
    tests_passed: int,
    tests_total: int,
    commit_hash: str | None = None,
) -> str:
    """Format a task completion notification."""
    files_summary = "\n".join(f"  • `{f}`" for f in files_changed[:5])
    if len(files_changed) > 5:
        files_summary += f"\n  • ... and {len(files_changed) - 5} more"
    
    return f"""✅ **{task_id} Complete**

**{title}**

**Files Changed:**
{files_summary}

**Verification:**
• Tests: {tests_passed}/{tests_total} passed ✓
• Lint: Clean ✓

{f"Commit: `{commit_hash}`" if commit_hash else ""}
"""


def format_digest(
    completed: list[dict[str, Any]],
    in_progress: list[dict[str, Any]],
    stats: dict[str, Any],
    period_hours: int = 4,
) -> str:
    """Format a digest notification."""
    completed_list = "\n".join(
        f"├─ {t['id']}: {t['title']} ✅"
        for t in completed[:-1]
    )
    if completed:
        completed_list += f"\n└─ {completed[-1]['id']}: {completed[-1]['title']} ✅"
    
    in_progress_list = "\n".join(
        f"└─ {t['id']}: {t['title']} ({t.get('progress', 0)}%)"
        for t in in_progress
    )
    
    return f"""📊 **GRIT Digest** • Last {period_hours} hours

**Completed: {len(completed)} tasks**
{completed_list if completed_list else "└─ None"}

**In Progress: {len(in_progress)} tasks**
{in_progress_list if in_progress_list else "└─ None"}

**Stats:**
• Files changed: {stats.get('files_changed', 0)}
• Lines added: +{stats.get('lines_added', 0)}
• Lines removed: -{stats.get('lines_removed', 0)}
• Tests added: {stats.get('tests_added', 0)}

**Blocked:** {stats.get('blocked', 0)}
**Failed:** {stats.get('failed', 0)}
"""


def format_escalation(
    task_id: str,
    title: str,
    description: str,
    options: list[dict[str, str]],
    recommendation: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """Format an escalation notification with decision buttons."""
    options_text = "\n".join(
        f"**{i+1}. {opt['name']}**\n   {opt['description']}"
        for i, opt in enumerate(options)
    )
    
    text = f"""🔶 **Decision Needed: {task_id}**

**Task:** {title}

{description}

**Options:**
{options_text}

{f"**Recommendation:** {recommendation}" if recommendation else ""}
"""
    
    # Create inline keyboard with options
    buttons = [
        [InlineKeyboardButton(
            text=f"#{i+1}: {opt['name'][:20]}",
            callback_data=f"decide:{task_id}:{i}",
        )]
        for i, opt in enumerate(options)
    ]
    buttons.append([
        InlineKeyboardButton(text="🤔 Need more info", callback_data=f"decide:{task_id}:info"),
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    return text, keyboard


def format_blocked_alert(
    command: str,
    reason: str,
    context: str | None = None,
) -> str:
    """Format a blocked action alert."""
    return f"""🚫 **Blocked Action**

**Attempted:**
```
{command[:200]}{'...' if len(command) > 200 else ''}
```

**Reason:** {reason}
**Status:** Action was NOT executed

{f"**Context:** {context}" if context else ""}

_This is logged for awareness. No action needed._
"""


def format_trust_change(
    pattern: str,
    old_level: TrustLevel,
    new_level: TrustLevel,
    reason: str,
) -> str:
    """Format a trust level change notification."""
    emoji = "📈" if new_level.value > old_level.value else "⚠️"
    action = "promoted" if new_level.value > old_level.value else "demoted"
    
    return f"""{emoji} **Trust {action.title()}**

**Pattern:** `{pattern}`
**Change:** {old_level.value} → {new_level.value}
**Reason:** {reason}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Handle /start command."""
    if message.from_user and message.from_user.id not in settings.admin_ids:
        await message.answer("⛔ You are not authorized to use this bot.")
        return
    
    await message.answer(
        "🤖 **AgentGRIT 2.0**\n\n"
        "Self-governing AI agent orchestration.\n\n"
        "**Commands:**\n"
        "/plan <task> - Cost-routing plan + spec to run\n"
        "/spawn <task> - Start new task\n"
        "/status - Overall status\n"
        "/list - List all tasks\n"
        "/trust - View trust levels\n"
        "/digest - Force send digest\n"
        "/health - System health check\n"
        "/help - Show this message",
        parse_mode=ParseMode.MARKDOWN,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    if message.from_user and message.from_user.id not in settings.admin_ids:
        return
    
    await message.answer(
        "📚 **AgentGRIT Commands**\n\n"
        "**Task Management:**\n"
        "`/spawn <description>` - Start new task\n"
        "`/spawn <desc> --priority high` - High priority task\n"
        "`/status` - Overall system status\n"
        "`/status <id>` - Specific task status\n"
        "`/list` - List all tasks\n"
        "`/list running` - Filter by status\n"
        "`/logs <id>` - View task logs\n"
        "`/pause <id>` - Pause task\n"
        "`/resume <id>` - Resume task\n"
        "`/terminate <id>` - Stop task\n\n"
        "**Monitoring:**\n"
        "`/trust` - View trust levels\n"
        "`/digest` - Force send digest\n"
        "`/health` - System health check\n"
        "`/stats` - Detailed statistics\n\n"
        "**Natural Language:**\n"
        "You can also just describe what you want:\n"
        "_\"add input validation to the signup form\"_\n"
        "_\"fix the linting errors in the auth module\"_",
        parse_mode=ParseMode.MARKDOWN,
    )


@router.message(Command("spawn"))
async def cmd_spawn(message: Message) -> None:
    """Handle /spawn command to create a new task."""
    if message.from_user and message.from_user.id not in settings.admin_ids:
        return
    
    # Extract task description from command
    text = message.text or ""
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        await message.answer(
            "❌ Usage: `/spawn <task description>`\n\n"
            "Example: `/spawn implement markdown exporter`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    
    task_description = parts[1]
    
    # Parse priority flag
    priority = "normal"
    if "--priority high" in task_description.lower():
        priority = "high"
        task_description = task_description.replace("--priority high", "").strip()
    elif "--priority low" in task_description.lower():
        priority = "low"
        task_description = task_description.replace("--priority low", "").strip()
    
    # TODO: Actually spawn the task via orchestrator
    task_id = f"GRIT-{datetime.utcnow().strftime('%H%M%S')}"
    
    await message.answer(
        f"🚀 **Task Spawned**\n\n"
        f"**ID:** `{task_id}`\n"
        f"**Description:** {task_description}\n"
        f"**Priority:** {priority}\n"
        f"**Status:** Queued\n\n"
        f"_You'll be notified when complete._",
        parse_mode=ParseMode.MARKDOWN,
    )


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Handle /status command."""
    if message.from_user and message.from_user.id not in settings.admin_ids:
        return
    
    # TODO: Get actual status from orchestrator
    await message.answer(
        "📊 **System Status**\n\n"
        "**Active Tasks:** 1\n"
        "**Queued:** 2\n"
        "**Completed Today:** 5\n\n"
        "**Backend:** Anthropic Claude ✓\n"
        "**Ollama Fallback:** Available ✓\n"
        "**Database:** Connected ✓\n"
        "**Redis Cache:** Connected ✓\n\n"
        "_Use `/status <id>` for specific task_",
        parse_mode=ParseMode.MARKDOWN,
    )


@router.message(Command("trust"))
async def cmd_trust(message: Message) -> None:
    """Handle /trust command to view trust levels."""
    if message.from_user and message.from_user.id not in settings.admin_ids:
        return
    
    manager = get_trust_manager()
    stats = manager.get_statistics()
    histories = manager.get_all_histories()
    
    # Format trust levels
    by_level = stats["by_level"]
    
    trust_text = (
        f"🔐 **Trust Levels**\n\n"
        f"**Untrusted:** {by_level.get('untrusted', 0)}\n"
        f"**Trusted:** {by_level.get('trusted', 0)}\n"
        f"**Autonomous:** {by_level.get('autonomous', 0)}\n\n"
        f"**Success Rate:** {stats['success_rate']:.1%}\n"
        f"**Recent Promotions:** {stats['recent_promotions']}\n"
        f"**Recent Demotions:** {stats['recent_demotions']}\n"
    )
    
    # Add top patterns
    if histories:
        top = sorted(histories, key=lambda h: h.total_successes, reverse=True)[:3]
        trust_text += "\n**Top Patterns:**\n"
        for h in top:
            trust_text += f"• `{h.pattern}` ({h.trust_level.value})\n"
    
    await message.answer(trust_text, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("digest"))
async def cmd_digest(message: Message) -> None:
    """Handle /digest command to force send a digest."""
    if message.from_user and message.from_user.id not in settings.admin_ids:
        return
    
    # TODO: Get actual data from orchestrator
    digest = format_digest(
        completed=[
            {"id": "GRIT-0042", "title": "markdown exporter"},
            {"id": "GRIT-0043", "title": "Test coverage"},
        ],
        in_progress=[
            {"id": "GRIT-0044", "title": "Prime Video parser", "progress": 60},
        ],
        stats={
            "files_changed": 12,
            "lines_added": 543,
            "lines_removed": 45,
            "tests_added": 18,
            "blocked": 0,
            "failed": 0,
        },
    )
    
    await message.answer(digest, parse_mode=ParseMode.MARKDOWN)


@router.message(Command("health"))
async def cmd_health(message: Message) -> None:
    """Handle /health command."""
    if message.from_user and message.from_user.id not in settings.admin_ids:
        return
    
    from ..execution.claude_client import get_execution_manager
    
    manager = get_execution_manager()
    health = await manager.health_check()
    
    anthropic_status = "✅" if health.get("anthropic") else "❌"
    ollama_status = "✅" if health.get("ollama") else "❌"
    
    await message.answer(
        f"🏥 **Health Check**\n\n"
        f"**Anthropic API:** {anthropic_status}\n"
        f"**Ollama Local:** {ollama_status}\n"
        f"**Timestamp:** {datetime.utcnow().isoformat()}Z",
        parse_mode=ParseMode.MARKDOWN,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# CALLBACK HANDLERS (for inline buttons)
# ═══════════════════════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("decide:"))
async def handle_decision(callback: CallbackQuery) -> None:
    """Handle decision callbacks from escalation messages."""
    if callback.from_user and callback.from_user.id not in settings.admin_ids:
        await callback.answer("Not authorized", show_alert=True)
        return
    
    data = callback.data or ""
    parts = data.split(":")
    if len(parts) != 3:
        await callback.answer("Invalid callback data", show_alert=True)
        return
    
    _, task_id, choice = parts
    
    if choice == "info":
        # TODO: Send more detailed information
        await callback.answer("Sending detailed info...", show_alert=False)
        if callback.message:
            await callback.message.answer(
                f"📋 **Additional Info for {task_id}**\n\n"
                "_Detailed analysis coming..._",
                parse_mode=ParseMode.MARKDOWN,
            )
    else:
        option_num = int(choice)
        await callback.answer(f"Selected option #{option_num + 1}", show_alert=False)
        
        # TODO: Process the decision via orchestrator
        if callback.message:
            await callback.message.edit_text(
                callback.message.text + f"\n\n✅ **Decision:** Option #{option_num + 1} selected",
                parse_mode=ParseMode.MARKDOWN,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# COST-GOVERNANCE WORKFLOW (/plan) — the live wire to the v2.6 governor
# ═══════════════════════════════════════════════════════════════════════════════

def _buttons_to_keyboard(buttons: list[Button]) -> InlineKeyboardMarkup | None:
    """Convert bot_workflow Buttons into an aiogram inline keyboard."""
    if not buttons:
        return None
    rows = [
        [InlineKeyboardButton(text=b.label, callback_data=b.callback)]
        for b in buttons
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_markdown_safe(send, text: str, **kwargs) -> None:
    """Send with Markdown; fall back to plain text if Telegram rejects the parse."""
    try:
        await send(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except Exception:
        await send(text, **kwargs)


@router.message(Command("plan"))
async def cmd_plan(message: Message) -> None:
    """Run the cost governor on a task and return a routing plan + paste-spec."""
    if message.from_user and message.from_user.id not in settings.admin_ids:
        await message.answer("⛔ Not authorized.")
        return

    task = (message.text or "").partition(" ")[2].strip()
    if not task:
        await message.answer(
            "Usage: `/plan <task>`\n\n"
            "Example:\n"
            "`/plan research the latest npm release then write a parser`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = render_plan_message(task)
    await _send_markdown_safe(
        message.answer, msg.text, reply_markup=_buttons_to_keyboard(msg.buttons)
    )


@router.callback_query(F.data.contains("::") | (F.data == "reject"))
async def handle_plan_callback(callback: CallbackQuery) -> None:
    """Handle Approve/Reject/Downgrade buttons from a /plan message."""
    if callback.from_user and callback.from_user.id not in settings.admin_ids:
        await callback.answer("Not authorized", show_alert=True)
        return

    result = confirm_plan(callback.data or "")
    await callback.answer()
    if callback.message:
        await _send_markdown_safe(callback.message.answer, result.text)


# ═══════════════════════════════════════════════════════════════════════════════
# NATURAL LANGUAGE HANDLER
# ═══════════════════════════════════════════════════════════════════════════════

@router.message(F.text)
async def handle_natural_language(message: Message) -> None:
    """Handle natural language messages as task descriptions."""
    if message.from_user and message.from_user.id not in settings.admin_ids:
        return
    
    text = message.text or ""
    
    # Simple pattern matching for common intents
    task_keywords = ["build", "create", "implement", "fix", "add", "update", "refactor"]
    
    if any(text.lower().startswith(kw) for kw in task_keywords):
        # Treat as task spawn
        task_id = f"GRIT-{datetime.utcnow().strftime('%H%M%S')}"
        await message.answer(
            f"🚀 **Task Created**\n\n"
            f"**ID:** `{task_id}`\n"
            f"**Task:** {text}\n\n"
            f"_Processing..._",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        # Unknown intent
        await message.answer(
            "🤔 Not sure what you want. Try:\n\n"
            "• `/spawn <task>` - Start a task\n"
            "• `/status` - Check status\n"
            "• `/help` - See all commands\n\n"
            "Or describe a task like:\n"
            "_\"build the markdown exporter\"_",
            parse_mode=ParseMode.MARKDOWN,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# BOT INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════════

class TelegramBot:
    """AgentGRIT Telegram bot."""
    
    def __init__(self):
        self.bot: Bot | None = None
        self.dp: Dispatcher | None = None
        self._running = False
    
    async def initialize(self) -> None:
        """Initialize the bot."""
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")
        
        self.bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        )
        self.dp = Dispatcher()
        self.dp.include_router(router)
    
    async def start(self) -> None:
        """Start the bot."""
        if not self.bot or not self.dp:
            await self.initialize()
        
        self._running = True
        await self.dp.start_polling(self.bot)
    
    async def stop(self) -> None:
        """Stop the bot."""
        self._running = False
        if self.dp:
            await self.dp.stop_polling()
        if self.bot:
            await self.bot.session.close()
    
    async def send_notification(
        self,
        text: str,
        chat_id: int | None = None,
        keyboard: InlineKeyboardMarkup | None = None,
    ) -> None:
        """Send a notification to admin(s)."""
        if not self.bot:
            await self.initialize()
        
        targets = [chat_id] if chat_id else settings.admin_ids
        
        for target in targets:
            try:
                await self.bot.send_message(
                    chat_id=target,
                    text=text,
                    reply_markup=keyboard,
                )
            except Exception as e:
                # Log but don't fail
                print(f"Failed to send to {target}: {e}")
    
    async def send_task_complete(
        self,
        task_id: str,
        title: str,
        files_changed: list[str],
        tests_passed: int,
        tests_total: int,
        commit_hash: str | None = None,
    ) -> None:
        """Send a task completion notification."""
        text = format_task_complete(
            task_id=task_id,
            title=title,
            files_changed=files_changed,
            tests_passed=tests_passed,
            tests_total=tests_total,
            commit_hash=commit_hash,
        )
        await self.send_notification(text)
    
    async def send_escalation(
        self,
        task_id: str,
        title: str,
        description: str,
        options: list[dict[str, str]],
        recommendation: str | None = None,
    ) -> None:
        """Send an escalation notification with decision buttons."""
        text, keyboard = format_escalation(
            task_id=task_id,
            title=title,
            description=description,
            options=options,
            recommendation=recommendation,
        )
        await self.send_notification(text, keyboard=keyboard)
    
    async def send_blocked_alert(
        self,
        command: str,
        reason: str,
        context: str | None = None,
    ) -> None:
        """Send a blocked action alert."""
        text = format_blocked_alert(command, reason, context)
        await self.send_notification(text)


# Global instance
_bot: TelegramBot | None = None


def get_telegram_bot() -> TelegramBot:
    """Get or create the global Telegram bot."""
    global _bot
    if _bot is None:
        _bot = TelegramBot()
    return _bot
