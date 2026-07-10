"""AgentGRIT 2.0 - Main Entry Point

The Ultimate AI Agent: Agent Zero + Ollama + GRIT Bylaws

Usage:
    python -m src.main                    # Start all services (API + Telegram + Agents)
    python -m src.main --api-only         # API server only
    python -m src.main --bot-only         # Telegram bot only
    python -m src.main --cli              # Interactive CLI
    python -m src.main --agents-only      # Run agents without API/Telegram
    python -m src.main --agent example    # Run a specific registered agent
    python -m src.main --dry-run          # Agents run but don't execute (log only)
"""

import argparse
import asyncio
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import settings
from .agents.grit_agent import LLMProvider, LLMConfig, MultiLLMRouter

console = Console()


# =============================================================================
# STARTUP DISPLAY
# =============================================================================

def print_banner():
    """Print startup banner with status."""
    banner = Text()
    banner.append("AgentGRIT", style="bold cyan")
    banner.append(" v2.0.0\n", style="dim")
    banner.append("The Ultimate AI Agent Framework\n\n", style="italic")

    # Show LLM status
    llms = [
        ("Ollama", settings.ollama_enabled, "FREE"),
        ("Perplexity", bool(settings.pplx_api_key), "$5/mo"),
        ("Grok", bool(getattr(settings, 'grok_api_key', None)), "Premium"),
        ("Claude", bool(settings.anthropic_api_key), "$$$"),
    ]

    for name, enabled, cost in llms:
        status = "\u2713" if enabled else "\u2717"
        color = "green" if enabled else "red"
        banner.append(f"  {status} {name}", style=color)
        banner.append(f" ({cost})\n", style="dim")

    console.print(Panel(banner, title="Starting Up", border_style="cyan"))


def print_routing_table():
    """Show how tasks will be routed."""
    table = Table(title="LLM Routing Strategy")
    table.add_column("Task Type", style="cyan")
    table.add_column("Routes To", style="green")
    table.add_column("Cost", style="yellow")

    routes = [
        ("Simple code, formatting", "Ollama", "FREE"),
        ("Research, docs, web search", "Perplexity", "~$0.001"),
        ("X/Twitter, social context", "Grok", "Subscription"),
        ("Complex architecture", "Claude Sonnet", "~$0.003"),
        ("Critical decisions", "Claude Opus", "~$0.015"),
    ]

    for task, provider, cost in routes:
        table.add_row(task, provider, cost)

    console.print(table)


# =============================================================================
# LLM CONFIGURATION
# =============================================================================

def build_llm_configs() -> dict[LLMProvider, LLMConfig]:
    """Build LLM configurations from settings."""
    configs = {}

    # Ollama (Priority 1 - FREE)
    configs[LLMProvider.OLLAMA] = LLMConfig(
        provider=LLMProvider.OLLAMA,
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        enabled=settings.ollama_enabled,
    )

    # Perplexity (Priority 2 - $5/mo)
    if settings.pplx_api_key:
        configs[LLMProvider.PERPLEXITY] = LLMConfig(
            provider=LLMProvider.PERPLEXITY,
            api_key=settings.pplx_api_key,
            enabled=True,
        )

    # Grok (Priority 3 - Premium)
    grok_key = getattr(settings, 'grok_api_key', None) or getattr(settings, 'xai_api_key', None)
    if grok_key:
        configs[LLMProvider.GROK] = LLMConfig(
            provider=LLMProvider.GROK,
            api_key=grok_key,
            enabled=True,
        )

    # Claude (Priority 4 - Expensive)
    if settings.anthropic_api_key:
        configs[LLMProvider.CLAUDE] = LLMConfig(
            provider=LLMProvider.CLAUDE,
            api_key=settings.anthropic_api_key,
            model=settings.primary_model,
            enabled=True,
        )

    return configs


# =============================================================================
# SERVICE RUNNERS
# =============================================================================

async def run_api_server():
    """Run the FastAPI server."""
    import uvicorn
    from .api.server import app

    config = uvicorn.Config(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_telegram_bot(escalation_manager=None):
    """Run the hardened Telegram bot with escalation support."""
    # Import hardened version (NOT the old telegram.py)
    from .bot.telegram_hardened import create_hardened_bot

    if not settings.telegram_bot_token:
        console.print("[yellow]Telegram bot not configured (skipping)[/yellow]")
        return

    bot = create_hardened_bot(
        token=settings.telegram_bot_token,
        admin_ids=settings.admin_ids,
        escalation_manager=escalation_manager,
    )

    if bot:
        await bot.start()
    else:
        console.print("[red]Failed to create Telegram bot[/red]")


# =============================================================================
# AGENT ORCHESTRATOR (The Integration Gap Fix)
# =============================================================================

class AgentOrchestrator:
    """
    Orchestrates agent lifecycle with escalation and planning integration.

    This is the "integration gap" fix - wires agents to:
    - EscalationManager for approvals
    - SessionFileManager for planning
    - Telegram for notifications

    AVAILABLE_AGENTS ships with one entry: the template agent
    (src/agents/example_agent.py). Register your own agents here as you
    build them -- add a name + description to AVAILABLE_AGENTS and a
    _run_<name> method below following the _run_example pattern.
    """

    AVAILABLE_AGENTS = {
        "example": "Template agent -- copy src/agents/example_agent.py to build your own",
        "repo_steward": (
            "Governed repo advisor: gardener.tend + skill discovery + autonomy-gated "
            "remediation proposals (no auto-edit). CLI: python -m src.agents.repo_steward_agent"
        ),
        "legal_research": (
            "Governed legal-research advisor for a licensed attorney (public-record "
            "CourtListener only; cite-or-refuse; never files). "
            "CLI: python -m src.agents.legal_research_agent"
        ),
    }

    def __init__(
        self,
        escalation_manager,
        session_manager,
        llm_configs: dict,
        dry_run: bool = False,
    ):
        self.escalation_manager = escalation_manager
        self.session_manager = session_manager
        self.llm_configs = llm_configs
        self.dry_run = dry_run
        self.running_agents: dict[str, asyncio.Task] = {}
        self.shutdown_event = asyncio.Event()

    async def start_agent(self, agent_name: str) -> asyncio.Task | None:
        """Start a specific agent."""
        if agent_name not in self.AVAILABLE_AGENTS:
            console.print(f"[red]Unknown agent: {agent_name}[/red]")
            console.print(f"Available: {', '.join(self.AVAILABLE_AGENTS.keys())}")
            return None

        if agent_name in self.running_agents:
            console.print(f"[yellow]Agent {agent_name} already running[/yellow]")
            return self.running_agents[agent_name]

        # Initialize task plan for this agent run
        task_id = f"{agent_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self.session_manager.init_session(
            task_id=task_id,
            description=f"Autonomous {agent_name} agent run",
            owner="orchestrator",
            risk_level="medium",
            acceptance_tests=[f"{agent_name} completes at least one cycle"],
        )

        # Create and start agent task
        if agent_name == "example":
            task = asyncio.create_task(
                self._run_example(task_id),
                name=f"agent_{agent_name}",
            )
        elif agent_name == "repo_steward":
            task = asyncio.create_task(
                self._run_repo_steward(task_id),
                name=f"agent_{agent_name}",
            )
        elif agent_name == "legal_research":
            task = asyncio.create_task(
                self._run_legal_research(task_id),
                name=f"agent_{agent_name}",
            )
        else:
            return None

        self.running_agents[agent_name] = task
        console.print(f"[green]\u2713[/green] Agent {agent_name} started (task: {task_id})")
        return task

    async def start_all_agents(self):
        """Start all available agents."""
        for agent_name in self.AVAILABLE_AGENTS:
            await self.start_agent(agent_name)

    async def stop_agent(self, agent_name: str):
        """Stop a specific agent gracefully."""
        if agent_name not in self.running_agents:
            return

        task = self.running_agents.pop(agent_name)
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        console.print(f"[yellow]Agent {agent_name} stopped[/yellow]")

    async def stop_all(self):
        """Stop all agents gracefully."""
        self.shutdown_event.set()
        for agent_name in list(self.running_agents.keys()):
            await self.stop_agent(agent_name)

    async def wait_for_shutdown(self):
        """Wait for shutdown signal."""
        await self.shutdown_event.wait()

    # -------------------------------------------------------------------
    # AGENT IMPLEMENTATIONS
    # -------------------------------------------------------------------

    async def _run_example(self, task_id: str):
        """Run the template agent with escalation integration. Copy this
        method's shape when you add your own agent."""
        from .agents.example_agent import TemplateAgent
        from .planning.session_files import ProgressEntry

        agent = TemplateAgent()

        cycle = 0
        while not self.shutdown_event.is_set():
            cycle += 1

            self.session_manager.append_progress(task_id, ProgressEntry(
                timestamp=datetime.utcnow(),
                agent_id="example",
                event_type="action",
                summary=f"Starting cycle {cycle}",
            ))

            if self.dry_run:
                console.print(f"[dim][DRY-RUN] example agent cycle {cycle}[/dim]")
                await asyncio.sleep(60)
                continue

            try:
                result = await agent.run_once(task="describe your task here")
                self.session_manager.append_progress(task_id, ProgressEntry(
                    timestamp=datetime.utcnow(),
                    agent_id="example",
                    event_type="action",
                    summary=f"Cycle {cycle}: {result.get('status')}",
                ))
            except Exception as e:
                self.session_manager.append_progress(task_id, ProgressEntry(
                    timestamp=datetime.utcnow(),
                    agent_id="example",
                    event_type="error",
                    summary=f"Cycle {cycle} failed: {str(e)[:100]}",
                ))
                console.print(f"[red]example agent error: {e}[/red]")

            try:
                await asyncio.wait_for(
                    self.shutdown_event.wait(),
                    timeout=7200,
                )
            except asyncio.TimeoutError:
                pass  # Continue to next cycle

    async def _run_repo_steward(self, task_id: str):
        """Run the Repo Steward advisor on the current working tree.

        Composes gardener + skill_discovery + autonomy + decision_record.
        Never auto-edits. Failures are logged; the orchestrator keeps running.
        """
        from .agents.repo_steward_agent import RepoStewardAgent
        from .planning.session_files import ProgressEntry
        from pathlib import Path

        agent = RepoStewardAgent()
        target = Path.cwd()

        cycle = 0
        while not self.shutdown_event.is_set():
            cycle += 1
            self.session_manager.append_progress(task_id, ProgressEntry(
                timestamp=datetime.utcnow(),
                agent_id="repo_steward",
                event_type="action",
                summary=f"Starting steward cycle {cycle} on {target}",
            ))

            if self.dry_run:
                console.print(
                    f"[dim][DRY-RUN] repo_steward cycle {cycle} on {target}[/dim]"
                )
                await asyncio.sleep(60)
                continue

            try:
                result = await agent.run_once(
                    task=f"steward inspect {target}",
                    target=target,
                )
                summary = (
                    f"Cycle {cycle}: {result.get('status')} "
                    f"findings={(result.get('evidence') or {}).get('finding_count')} "
                    f"decision={(result.get('evidence') or {}).get('decision_disposition')}"
                )
                self.session_manager.append_progress(task_id, ProgressEntry(
                    timestamp=datetime.utcnow(),
                    agent_id="repo_steward",
                    event_type="action",
                    summary=summary[:200],
                ))
                report = (result.get("evidence") or {}).get("report") or ""
                if report:
                    console.print(report[:2000])
            except Exception as e:
                self.session_manager.append_progress(task_id, ProgressEntry(
                    timestamp=datetime.utcnow(),
                    agent_id="repo_steward",
                    event_type="error",
                    summary=f"Cycle {cycle} failed: {str(e)[:100]}",
                ))
                console.print(f"[red]repo_steward error: {e}[/red]")

            try:
                await asyncio.wait_for(
                    self.shutdown_event.wait(),
                    timeout=7200,
                )
            except asyncio.TimeoutError:
                pass

    async def _run_legal_research(self, task_id: str):
        """Run the legal-research advisor (public-record, attorney-tool only).

        Never files/serves/sends. Failures are logged; orchestrator keeps running.
        The orchestrator loop uses a fixed demo question; one-shot CLI is preferred.
        """
        from .agents.legal_research_agent import LegalResearchAgent
        from .planning.session_files import ProgressEntry

        agent = LegalResearchAgent()
        # Orchestrator does not hold confidential matter data — generic demo only.
        demo_q = (
            "case law research for counsel: public-record survey of "
            "qualified immunity at summary judgment"
        )

        cycle = 0
        while not self.shutdown_event.is_set():
            cycle += 1
            self.session_manager.append_progress(task_id, ProgressEntry(
                timestamp=datetime.utcnow(),
                agent_id="legal_research",
                event_type="action",
                summary=f"Starting legal_research cycle {cycle}",
            ))

            if self.dry_run:
                console.print(
                    f"[dim][DRY-RUN] legal_research cycle {cycle}[/dim]"
                )
                await asyncio.sleep(60)
                continue

            try:
                result = await agent.run_once(
                    task=demo_q,
                    attorney_confirmed=True,
                    skip_free_research=False,
                )
                summary = (
                    f"Cycle {cycle}: {result.get('status')} "
                    f"decision={(result.get('evidence') or {}).get('decision_disposition')} "
                    f"verdict={(result.get('evidence') or {}).get('evidence_verdict')}"
                )
                self.session_manager.append_progress(task_id, ProgressEntry(
                    timestamp=datetime.utcnow(),
                    agent_id="legal_research",
                    event_type="action",
                    summary=summary[:200],
                ))
                report = (result.get("evidence") or {}).get("report") or ""
                if report:
                    console.print(report[:2000])
            except Exception as e:
                self.session_manager.append_progress(task_id, ProgressEntry(
                    timestamp=datetime.utcnow(),
                    agent_id="legal_research",
                    event_type="error",
                    summary=f"Cycle {cycle} failed: {str(e)[:100]}",
                ))
                console.print(f"[red]legal_research error: {e}[/red]")

            try:
                await asyncio.wait_for(
                    self.shutdown_event.wait(),
                    timeout=7200,
                )
            except asyncio.TimeoutError:
                pass


# =============================================================================
# AGENT RUNNER MODE
# =============================================================================

async def run_agents(
    agent_name: str | None = None,
    dry_run: bool = False,
    with_telegram: bool = True,
):
    """
    Run agent orchestrator with optional Telegram control plane.

    This is the main "autonomous mode" entry point.
    """
    from .governance.escalations import EscalationManager
    from .planning.session_files import SessionFileManager

    # Initialize shared infrastructure
    escalation_manager = EscalationManager(
        log_dir=Path("logs"),
        owner_telegram_ids=settings.admin_ids,
    )

    session_manager = SessionFileManager(
        plans_dir=Path("plans"),
    )

    llm_configs = build_llm_configs()

    # Create orchestrator
    orchestrator = AgentOrchestrator(
        escalation_manager=escalation_manager,
        session_manager=session_manager,
        llm_configs=llm_configs,
        dry_run=dry_run,
    )

    tasks = []

    # Start agents
    if agent_name:
        await orchestrator.start_agent(agent_name)
    else:
        console.print(
            "[yellow]No --agent specified.[/yellow] "
            f"Available: {', '.join(orchestrator.AVAILABLE_AGENTS.keys())}\n"
            "Register your own agent in AgentOrchestrator.AVAILABLE_AGENTS "
            "(see src/agents/example_agent.py) and pass --agent <name>."
        )
        return

    # Optionally start Telegram as control plane
    if with_telegram and settings.telegram_bot_token:
        # Wire escalation notifications to Telegram
        def notify_telegram(message: str):
            # This will be called when escalations need Owner approval
            console.print(f"[yellow]ESCALATION:[/yellow] {message[:100]}...")

        escalation_manager.set_notify_callback(notify_telegram)

        tasks.append(asyncio.create_task(
            run_telegram_bot(escalation_manager),
            name="telegram_bot",
        ))
        console.print("[green]\u2713[/green] Telegram control plane started")

    # Add agent tasks
    tasks.extend(orchestrator.running_agents.values())

    console.print("\n[bold green]Agents running![/bold green]")
    console.print("Press Ctrl+C to stop\n")

    # Setup graceful shutdown
    def handle_shutdown(sig, frame):
        console.print("\n[yellow]Shutdown requested...[/yellow]")
        asyncio.create_task(orchestrator.stop_all())

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Wait for all tasks
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        pass

    await orchestrator.stop_all()
    console.print("[bold]Agents stopped.[/bold]")


# =============================================================================
# COMBINED SERVICE MODE
# =============================================================================

async def run_all_services():
    """Run all AgentGRIT services concurrently (API + Telegram + Agents)."""
    from .governance.escalations import EscalationManager
    from .planning.session_files import SessionFileManager

    # Initialize shared infrastructure
    escalation_manager = EscalationManager(
        log_dir=Path("logs"),
        owner_telegram_ids=settings.admin_ids,
    )

    session_manager = SessionFileManager(
        plans_dir=Path("plans"),
    )

    llm_configs = build_llm_configs()

    tasks = []

    # API Server
    tasks.append(asyncio.create_task(run_api_server(), name="api_server"))
    console.print(f"[green]\u2713[/green] API server starting on port {settings.api_port}")

    # Telegram Bot (with escalation manager)
    if settings.telegram_bot_token:
        tasks.append(asyncio.create_task(
            run_telegram_bot(escalation_manager),
            name="telegram_bot",
        ))
        console.print("[green]\u2713[/green] Telegram bot starting (hardened)")

    # Agent Orchestrator -- no agent auto-started; register + run your own
    # via --agent <name> (see AgentOrchestrator.AVAILABLE_AGENTS).
    orchestrator = AgentOrchestrator(
        escalation_manager=escalation_manager,
        session_manager=session_manager,
        llm_configs=llm_configs,
    )

    tasks.extend(orchestrator.running_agents.values())

    console.print("\n[bold green]All services started![/bold green]\n")
    console.print("Press Ctrl+C to stop\n")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        console.print("\n[yellow]Shutting down services...[/yellow]")
        await orchestrator.stop_all()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


# =============================================================================
# CLI MODE
# =============================================================================

async def run_cli():
    """Run interactive CLI mode with escalation support."""
    from .agents.grit_agent import AgentGRIT
    from .governance.escalations import EscalationManager

    # Initialize escalation manager for CLI
    escalation_manager = EscalationManager(
        log_dir=Path("logs"),
        owner_telegram_ids=settings.admin_ids,
    )

    configs = build_llm_configs()
    agent = AgentGRIT(
        name="GRIT",
        llm_configs=configs,
        escalation_manager=escalation_manager,
    )

    console.print("\n[bold cyan]AgentGRIT Interactive CLI[/bold cyan]")
    console.print("Type 'quit' to exit, 'status' for usage stats")
    console.print("Type 'escalations' to view pending approvals\n")

    while True:
        try:
            user_input = console.input("[bold green]You:[/bold green] ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input:
            continue

        if user_input.lower() == "quit":
            break

        if user_input.lower() == "status":
            if agent.router:
                console.print(f"\n[cyan]Usage today:[/cyan]")
                for provider, count in agent.router.usage_tracker.items():
                    console.print(f"  {provider}: {count} requests")
            continue

        if user_input.lower() == "escalations":
            pending = escalation_manager.get_pending()
            if pending:
                console.print(f"\n[cyan]Pending escalations ({len(pending)}):[/cyan]")
                for esc in pending:
                    console.print(f"  {esc.id}: {esc.action.category.value} ({esc.risk_level.name})")
            else:
                console.print("[dim]No pending escalations[/dim]")
            continue

        # Process the input
        response = await agent.process(user_input)
        console.print(f"\n[bold blue]GRIT:[/bold blue] {response}\n")

    console.print("\n[bold]Goodbye![/bold]")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description="AgentGRIT 2.0 - The Ultimate AI Agent Framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.main                    Start all services (API + Telegram + Agents)
  python -m src.main --cli              Interactive command line
  python -m src.main --api-only         API server only
  python -m src.main --bot-only         Telegram bot only
  python -m src.main --agents-only      Run agents without API/Telegram
  python -m src.main --agent example    Run a specific registered agent
  python -m src.main --dry-run          Agents run but don't execute
        """,
    )

    parser.add_argument(
        "--cli", action="store_true",
        help="Run interactive CLI mode",
    )
    parser.add_argument(
        "--api-only", action="store_true",
        help="Run API server only",
    )
    parser.add_argument(
        "--bot-only", action="store_true",
        help="Run Telegram bot only",
    )
    parser.add_argument(
        "--agents-only", action="store_true",
        help="Run agent orchestrator only (no API/Telegram)",
    )
    parser.add_argument(
        "--agent", type=str, metavar="NAME",
        help="Run a specific registered agent (see AgentOrchestrator.AVAILABLE_AGENTS)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Agents run but don't execute real actions",
    )
    parser.add_argument(
        "--no-banner", action="store_true",
        help="Skip the startup banner",
    )

    args = parser.parse_args()

    # Show banner
    if not args.no_banner:
        print_banner()
        print_routing_table()

    # Validate configuration
    configs = build_llm_configs()
    if not any(c.enabled for c in configs.values()):
        console.print(
            "[red]Error:[/red] No LLM backend configured.\n"
            "Enable OLLAMA or add API keys in .env"
        )
        sys.exit(1)

    # Ensure data directories exist
    Path("./data").mkdir(exist_ok=True)
    Path("./logs").mkdir(exist_ok=True)
    Path("./plans").mkdir(exist_ok=True)

    # Run the appropriate mode
    try:
        if args.cli:
            asyncio.run(run_cli())
        elif args.api_only:
            asyncio.run(run_api_server())
        elif args.bot_only:
            asyncio.run(run_telegram_bot())
        elif args.agents_only or args.agent:
            asyncio.run(run_agents(
                agent_name=args.agent,
                dry_run=args.dry_run,
                with_telegram=not args.agents_only,  # Include Telegram unless --agents-only
            ))
        else:
            asyncio.run(run_all_services())
    except KeyboardInterrupt:
        console.print("\n[bold]Goodbye![/bold]")


if __name__ == "__main__":
    main()
