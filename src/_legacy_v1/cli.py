#!/usr/bin/env python3
"""
AI Security Monitor - Command Line Interface
Zero-cost monitoring for AI technology launches and cybersecurity news.
"""

import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from monitor import AISecurityMonitor, run_fetch_job, run_digest_job


def cmd_analyze(args):
    """Run AI analysis on unanalyzed entries."""
    print(f"Running AI analysis on recent entries...")
    monitor = AISecurityMonitor(args.config)
    since_dt = None
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"Invalid date format: {args.since}. Use ISO format (YYYY-MM-DD).")
            sys.exit(1)
    results = monitor.run_analysis(since=since_dt, limit=args.limit)
    print(f"\nResults:")
    print(f"  Analyzed: {results['analyzed']}")
    print(f"  Failed:   {results['failed']}")
    print(f"  High Velocity (>=70): {results['high_velocity']}")


def cmd_enriched_digest(args):
    """Generate and send AI-enriched digest."""
    print(f"Generating {args.schedule} enriched digest via {args.method}...")

    monitor = AISecurityMonitor(args.config)
    
    # Parse since date if provided
    since_dt = None
    if args.since:
        try:
            since_dt = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"Invalid date format: {args.since}. Use ISO format (YYYY-MM-DD).")
            sys.exit(1)

    # First run analysis to enrich entries
    print("Running AI analysis to enrich digest...")
    monitor.run_analysis(since=since_dt, limit=args.limit)

    # Then generate enriched digest
    digest = monitor.generate_enriched_digest(since=since_dt, max_per_category=args.max_items)

    # Build delivery config from CLI args, fall back to config file
    delivery_config = {}
    if args.method == 'email':
        if args.email_user: delivery_config['username'] = args.email_user
        if args.email_pass: delivery_config['password'] = args.email_pass
        if args.from_email: delivery_config['from_email'] = args.from_email
        if args.to_email: delivery_config['to_email'] = args.to_email
        if args.smtp_server: delivery_config['smtp_server'] = args.smtp_server
        if args.smtp_port: delivery_config['smtp_port'] = args.smtp_port
    elif args.method == 'slack':
        if args.slack_webhook: delivery_config['webhook_url'] = args.slack_webhook
        if args.slack_channel: delivery_config['channel'] = args.slack_channel
    elif args.method == 'telegram':
        if args.telegram_token: delivery_config['bot_token'] = args.telegram_token
        if args.telegram_chat: delivery_config['chat_id'] = args.telegram_chat

    # Fall back to config file if CLI args not provided
    if not delivery_config:
        config_delivery = monitor.config.get('delivery', {}).get(args.method, {})
        delivery_config.update(config_delivery)

    # Send via delivery method
    from src.delivery import get_delivery
    delivery = get_delivery(args.method, delivery_config)

    subject = f"AI & Security Digest (Enriched) - {datetime.now().strftime('%Y-%m-%d')}"
    success = delivery.send(subject, digest['content'], digest['entries_by_category'])

    if success:
        print("✓ Enriched digest sent successfully")
    else:
        print("✗ Failed to send enriched digest")
        sys.exit(1)


def cmd_init(args):
    """Initialize database and config."""
    monitor = AISecurityMonitor(args.config)
    print("✓ Database initialized")
    print("✓ Sources loaded from config")
    stats = monitor.get_stats()
    print(f"✓ {stats['total_sources']} sources configured")
    print(f"✓ {stats['total_entries']} entries in database")


def cmd_fetch(args):
    """Fetch from all sources once."""
    print("Fetching from all sources...")
    monitor = AISecurityMonitor(args.config)
    results = monitor.fetch_all()
    print(f"\nResults:")
    print(f"  Success: {results['success']}")
    print(f"  Errors:  {results['error']}")
    print(f"  Skipped: {results['skipped']}")
    print(f"  New entries: {results['total_new']}")


def cmd_digest(args):
    """Generate and send digest."""
    print(f"Generating {args.schedule} digest via {args.method}...")

    # Build delivery config from command-line args (only non-None values)
    delivery_config = {}
    if args.method == 'email':
        if args.email_user: delivery_config['username'] = args.email_user
        if args.email_pass: delivery_config['password'] = args.email_pass
        if args.from_email: delivery_config['from_email'] = args.from_email
        if args.to_email: delivery_config['to_email'] = args.to_email
        if args.smtp_server: delivery_config['smtp_server'] = args.smtp_server
        if args.smtp_port: delivery_config['smtp_port'] = args.smtp_port
    elif args.method == 'slack':
        if args.slack_webhook: delivery_config['webhook_url'] = args.slack_webhook
        if args.slack_channel: delivery_config['channel'] = args.slack_channel
    elif args.method == 'telegram':
        if args.telegram_token: delivery_config['bot_token'] = args.telegram_token
        if args.telegram_chat: delivery_config['chat_id'] = args.telegram_chat

    monitor = AISecurityMonitor(args.config)
    success = monitor.send_digest(args.method, delivery_config)

    if success:
        print("✓ Digest sent successfully")
    else:
        print("✗ Failed to send digest")
        sys.exit(1)


def cmd_newspaper(args):
    """Generate and optionally send the 5-hour newspaper/newsletter."""
    import asyncio
    from ai_security_monitor.application.services.newspaper_service import NewspaperService
    from ai_security_monitor.infrastructure.delivery.base import delivery_registry
    from ai_security_monitor.config.settings import settings

    service = NewspaperService()
    print(f"Generating newspaper edition for window {args.window_hours} hours...")
    meta = asyncio.run(service.generate_edition(window_hours=args.window_hours))
    print(f"✓ Edition #{meta['edition_number']} compiled: {meta['total_threats']} threats analyzed.")
    print(f"  Markdown: {meta['md_path']}")
    print(f"  HTML:     {meta['html_path']}")
    print(f"  PDF:      {meta['pdf_path']}")

    # Telegram dispatch
    if args.telegram:
        bot_token = args.telegram_token or settings.delivery.telegram_bot_token or "8426550330:AAG5lxRf3qoVb6RbovH85rSgN42dO6Q4NlI"
        chat_id = args.telegram_chat or settings.delivery.telegram_chat_id or "1650972026"
        print(f"Dispatching newspaper PDF to Telegram chat {chat_id}...")
        tg_delivery = delivery_registry.create("telegram", {"bot_token": bot_token, "chat_id": chat_id})
        pdf_path = meta.get("pdf_path")
        if pdf_path:
            res = asyncio.run(tg_delivery.send_newspaper_document(
                pdf_path=pdf_path,
                edition_number=meta["edition_number"],
                lead_story=meta.get("lead_story", ""),
                total_threats=meta.get("total_threats", 0),
            ))
            if res.success:
                print(f"✓ Telegram dispatch succeeded: {res.message}")
            else:
                print(f"✗ Telegram dispatch failed: {res.error}")

    # Email dispatch
    if args.email:
        to_email = args.email
        print(f"Dispatching newspaper PDF to email {to_email}...")
        email_cfg = {
            "smtp_server": args.smtp_server or settings.delivery.email_smtp_server,
            "smtp_port": args.smtp_port or settings.delivery.email_smtp_port,
            "username": args.email_user or settings.delivery.email_username or "",
            "password": args.email_pass or settings.delivery.email_password or "",
            "from_email": args.from_email or settings.delivery.email_from or "noreply@aetherguard.ai",
            "to_email": to_email,
        }
        email_delivery = delivery_registry.create("email", email_cfg)
        pdf_path = meta.get("pdf_path")
        if pdf_path:
            res = asyncio.run(email_delivery.send_newspaper_pdf(
                pdf_path=pdf_path,
                edition_number=meta["edition_number"],
                to_email=to_email,
                lead_story=meta.get("lead_story", ""),
                total_threats=meta.get("total_threats", 0),
            ))
            if res.success:
                print(f"✓ Email dispatch succeeded: {res.message}")
            else:
                print(f"✗ Email dispatch failed: {res.error}")


def cmd_stats(args):
    """Show database statistics."""
    monitor = AISecurityMonitor(args.config)
    stats = monitor.get_stats()

    print("\n📊 Monitor Statistics")
    print("=" * 50)
    print(f"Total entries: {stats['total_entries']}")
    print(f"Active sources: {stats['total_sources']}")

    print("\nEntries by category:")
    for cat, count in stats['by_category'].items():
        print(f"  {cat}: {count}")

    print("\nRecent fetches (24h):")
    for fetch in stats['recent_fetches'][:10]:
        status_icon = "✓" if fetch['status'] == 'success' else "✗" if fetch['status'] == 'error' else "⏭"
        print(f"  {status_icon} {fetch['source_name']}: {fetch['entries_new']} new ({fetch['status']})")


def cmd_sources(args):
    """List configured sources."""
    monitor = AISecurityMonitor(args.config)
    sources = monitor.db.get_sources(enabled_only=not args.all)

    print(f"\n📡 Configured Sources ({len(sources)})")
    print("=" * 80)

    current_cat = None
    for src in sources:
        if src['category'] != current_cat:
            current_cat = src['category']
            print(f"\n{current_cat.upper()}:")

        status = "✓" if src['enabled'] else "✗"
        last = src['last_success'][:19] if src['last_success'] else 'Never'
        print(f"  {status} {src['name']} ({src['type']}) - Last: {last}")


def cmd_cleanup(args):
    """Clean up old entries."""
    monitor = AISecurityMonitor(args.config)
    deleted = monitor.cleanup(args.days)
    print(f"✓ Deleted {deleted} entries older than {args.days} days")


def cmd_test_delivery(args):
    """Test delivery method."""
    # Build delivery config from command-line args (only non-None values)
    delivery_config = {}
    if args.method == 'email':
        if args.email_user: delivery_config['username'] = args.email_user
        if args.email_pass: delivery_config['password'] = args.email_pass
        if args.from_email: delivery_config['from_email'] = args.from_email
        if args.to_email: delivery_config['to_email'] = args.to_email
        if args.smtp_server: delivery_config['smtp_server'] = args.smtp_server
        if args.smtp_port: delivery_config['smtp_port'] = args.smtp_port
    elif args.method == 'slack':
        if args.slack_webhook: delivery_config['webhook_url'] = args.slack_webhook
        if args.slack_channel: delivery_config['channel'] = args.slack_channel
    elif args.method == 'telegram':
        if args.telegram_token: delivery_config['bot_token'] = args.telegram_token
        if args.telegram_chat: delivery_config['chat_id'] = args.telegram_chat

    from src.delivery import get_delivery
    delivery = get_delivery(args.method, delivery_config)

    test_content = "This is a test message from AI Security Monitor."
    test_entries = {
        'ai_tech': [{
            'title': 'Test AI Article',
            'url': 'https://example.com',
            'summary': 'This is a test summary for the AI tech category.',
            'source_name': 'Test Source',
            'published_at': datetime.now(),
            'tags': ['test', 'ai'],
        }]
    }

    success = delivery.send("Test Digest", test_content, test_entries)
    if success:
        print(f"✓ Test {args.method} delivery successful")
    else:
        print(f"✗ Test {args.method} delivery failed")
        sys.exit(1)


def cmd_server(args):
    """Launch interactive real-time web dashboard."""
    import uvicorn
    print(f"🚀 Launching AI Security Monitor Web Command Center on http://{args.host}:{args.port}")
    uvicorn.run("src.server:app", host=args.host, port=args.port, reload=args.reload)


def cmd_strategy_init(args):
    """Initialize and populate the first generation of strategy genomes."""
    from database import get_db
    from ai_security_monitor.infrastructure.evolution.strategy_genome import create_evolution_engine

    db = get_db()
    engine = create_evolution_engine(db, population_size=args.population)
    population = engine.initialize_population()

    print(f"✓ Initialized strategy population with {len(population)} strategies")
    print(f"  Generation: {engine.generation}")

    # Run first generation benchmark
    if not args.skip_benchmark:
        print(f"\nRunning benchmark against last {args.test_entries} entries...")
        gen_result = engine.run_generation(test_limit=args.test_entries, elite_size=3)
        print(f"  Best fitness: {gen_result['best_fitness']:.4f}")
        print(f"  Avg fitness:  {gen_result['avg_fitness']:.4f}")

    # Save best strategy
    engine.save_best_strategy(args.strategy_name)
    best = engine.get_best_strategy()
    print(f"\n✓ Best strategy saved as '{args.strategy_name}'")
    print(f"  Fitness: {best.fitness_score:.4f}")
    print(f"  Genes: {json.dumps(best.genes, indent=2)}")


def cmd_strategy_evolve(args):
    """Evolve strategies through N generations."""
    from database import get_db
    from ai_security_monitor.infrastructure.evolution.strategy_genome import create_evolution_engine

    db = get_db()
    engine = create_evolution_engine(db, population_size=args.population)

    # Load existing best strategy as seed
    existing = engine.load_strategy(args.strategy_name)
    if existing:
        print(f"Loaded existing strategy '{args.strategy_name}' (fitness: {existing.fitness_score:.4f})")
        engine.initialize_population(seed_strategies=[existing])
    else:
        print("No existing strategy found. Initializing random population.")
        engine.initialize_population()

    for i in range(args.generations):
        print(f"\n--- Generation {engine.generation + 1} ---")
        gen_result = engine.run_generation(test_limit=args.test_entries, elite_size=3)
        print(f"  Best fitness: {gen_result['best_fitness']:.4f}")
        print(f"  Avg fitness:  {gen_result['avg_fitness']:.4f}")

    engine.save_best_strategy(args.strategy_name)
    best = engine.get_best_strategy()
    print(f"\n✓ Evolution complete. Best strategy saved as '{args.strategy_name}'")
    print(f"  Fitness: {best.fitness_score:.4f}")


def cmd_strategy_show(args):
    """Show the current best strategy."""
    from database import get_db
    from ai_security_monitor.infrastructure.evolution.strategy_genome import create_evolution_engine

    db = get_db()
    engine = create_evolution_engine(db)
    strategy = engine.load_strategy(args.strategy_name)

    if strategy is None:
        print(f"Strategy '{args.strategy_name}' not found. Run 'strategy-init' first.")
        sys.exit(1)

    print(f"\n📊 Strategy: {args.strategy_name}")
    print(f"{'=' * 60}")
    print(f"  Generation: {strategy.generation}")
    print(f"  Fitness:    {strategy.fitness_score:.4f}")
    print(f"\n  Genes:")
    for key, value in strategy.genes.items():
        print(f"    {key}: {value}")


def cmd_replay(args):
    """Replay historical entries with mutated strategies."""
    from database import get_db
    from ai_security_monitor.infrastructure.evolution.replay_harness import create_replay_manager
    from ai_security_monitor.infrastructure.evolution.strategy_genome import StrategyDna

    db = get_db()
    manager = create_replay_manager(db)

    print(f"Loading last {args.limit} entries for replay...")
    entries = manager.harness.load_entries(limit=args.limit)
    print(f"  Loaded {len(entries)} entries")

    if len(entries) == 0:
        print("No entries found. Run 'fetch' first.")
        sys.exit(1)

    # Load best strategy
    from ai_security_monitor.infrastructure.evolution.strategy_genome import create_evolution_engine
    engine = create_evolution_engine(db)
    best = engine.load_strategy(args.strategy_name)

    if best is None:
        print(f"Strategy '{args.strategy_name}' not found.")
        sys.exit(1)

    # Create a mutated variant
    mutated = best.mutate(mutation_rate=0.3, mutation_strength=0.2)
    print(f"\nComparing strategies:")
    print(f"  Original: gen={best.generation}, fitness={best.fitness_score:.4f}")
    print(f"  Mutated:  gen={mutated.generation}")

    comparisons = manager.harness.compare_strategies(entries, best, mutated)

    improvements = sum(1 for c in comparisons if c.improvement_score > 0)
    regressions = sum(1 for c in comparisons if c.improvement_score < 0)
    neutral = sum(1 for c in comparisons if c.improvement_score == 0)
    avg_improvement = sum(c.improvement_score for c in comparisons) / len(comparisons)

    print(f"\n  Results:")
    print(f"    Improved: {improvements}/{len(comparisons)}")
    print(f"    Regressed: {regressions}/{len(comparisons)}")
    print(f"    Neutral:  {neutral}/{len(comparisons)}")
    print(f"    Avg improvement: {avg_improvement:+.4f}")


def cmd_beliefs(args):
    """Show the system's epistemic beliefs."""
    from database import get_db
    from ai_security_monitor.infrastructure.epistemic.epistemic_engine import EpistemicEngine

    db = get_db()
    engine = EpistemicEngine(db)
    beliefs = engine.get_system_beliefs()

    print(f"\n🧠 System Beliefs")
    print(f"{'=' * 60}")
    print(f"  Total claims tracked: {beliefs['total_claims']}")

    print(f"\n  Claims by type:")
    for ct, count in beliefs['claims_by_type'].items():
        if count > 0:
            print(f"    {ct}: {count}")

    print(f"\n  Claims by method:")
    for method, count in beliefs['claims_by_method'].items():
        print(f"    {method}: {count}")

    if beliefs['top_confidence_claims']:
        print(f"\n  Top confidence claims:")
        for claim in beliefs['top_confidence_claims']:
            print(f"    [{claim['claim_type']}] {claim['target'][:50]}")
            print(f"      Raw: {claim['raw_confidence']:.3f} | Calibrated: {claim['calibrated_confidence']:.3f}")

    if beliefs['calibration_stats']:
        print(f"\n  Calibration stats:")
        for key, stats in beliefs['calibration_stats'].items():
            print(f"    {key}: {stats['total_outcomes']} outcomes, {stats['confirmed']} confirmed")


def cmd_opportunities(args):
    """Show detected improvement opportunities."""
    from database import get_db
    from ai_security_monitor.infrastructure.evolution.counterfactual_engine import create_counterfactual_engine

    db = get_db()
    engine = create_counterfactual_engine(db)
    report = engine.get_analysis_report()

    print(f"\n🔍 Opportunity Detection Report")
    print(f"{'=' * 60}")
    print(f"  Total decisions tracked: {report['total_decisions']}")
    print(f"  Patterns detected:       {report['patterns_detected']}")
    print(f"  Average regret:          {report['average_regret']:.4f} ({report['regret_assessment']})")

    if report['opportunities']:
        print(f"\n  Actionable Opportunities:")
        for opp in report['opportunities']:
            print(f"    [{opp['type']}] confidence={opp['confidence']:.2f}")
            print(f"    {opp['recommendation']}")


def cmd_validate_strategy(args):
    """Validate that a new strategy improves over the current one."""
    from database import get_db
    from ai_security_monitor.infrastructure.evolution.strategy_genome import create_evolution_engine
    from ai_security_monitor.infrastructure.evolution.replay_harness import create_replay_manager

    db = get_db()
    engine = create_evolution_engine(db)
    manager = create_replay_manager(db)

    current = engine.load_strategy(args.strategy_name)
    if current is None:
        print(f"Strategy '{args.strategy_name}' not found.")
        sys.exit(1)

    # Create a mutated variant for comparison
    variant = current.mutate(mutation_rate=0.4, mutation_strength=0.3)
    print(f"Validating mutated strategy against '{args.strategy_name}'...")
    print(f"  Test entries: {args.test_entries}")

    result = manager.validate_strategy_improvement(
        variant, current,
        test_limit=args.test_entries,
        min_improvement=args.min_improvement,
    )

    print(f"\n  Improvement: {result['improvement']:+.4f}")
    print(f"  Max regression: {result['max_regression']:+.4f}")
    print(f"  Avg latency: {result['avg_latency_ms']:.1f}ms")
    print(f"  Recommendation: {result['recommendation'].upper()}")

    details = result.get('details', {})
    if details:
        print(f"\n  Breakdown:")
        print(f"    Improved:  {details.get('entries_with_improvement', 0)}")
        print(f"    Regressed: {details.get('entries_with_regression', 0)}")
        print(f"    Neutral:   {details.get('entries_neutral', 0)}")


def main():
    parser = argparse.ArgumentParser(
        description='AI Security Monitor - Zero-cost monitoring for AI tech & cybersecurity',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Launch interactive web dashboard & real-time radar
  python -m cli server --port 8000

  # Initialize
  python -m cli init

  # Fetch once
  python -m cli fetch

  # Generate daily digest to console
  python -m cli digest --method console

  # Generate daily digest via email
  python -m cli digest --method email --to-email you@example.com --email-user you@gmail.com --email-pass 'app-password'

  # Generate weekly digest via Telegram
  python -m cli digest --schedule weekly --method telegram --telegram-token BOT_TOKEN --telegram-chat CHAT_ID

  # Show stats
  python -m cli stats

  # List sources
  python -m cli sources

  # Cleanup old entries (90 days)
  python -m cli cleanup --days 90
        """
    )

    parser.add_argument('-c', '--config', default='config/sources.yaml',
                        help='Path to config file (default: config/sources.yaml)')

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # server
    server_parser = subparsers.add_parser('server', help='Launch interactive real-time web dashboard')
    server_parser.add_argument('--host', default='0.0.0.0', help='Host IP (default: 0.0.0.0)')
    server_parser.add_argument('--port', type=int, default=8000, help='Port (default: 8000)')
    server_parser.add_argument('--reload', action='store_true', help='Enable auto-reload on code changes')

    # init
    subparsers.add_parser('init', help='Initialize database and load sources')

    # fetch
    subparsers.add_parser('fetch', help='Fetch from all sources once')

    # digest
    digest_parser = subparsers.add_parser('digest', help='Generate and send digest')
    digest_parser.add_argument('--schedule', choices=['daily', 'weekly'], default='daily',
                               help='Digest schedule (default: daily)')
    digest_parser.add_argument('--method', choices=['console', 'email', 'slack', 'telegram'],
                               default='console', help='Delivery method (default: console)')

    # Email args
    digest_parser.add_argument('--smtp-server', default='smtp.gmail.com', help='SMTP server')
    digest_parser.add_argument('--smtp-port', type=int, default=587, help='SMTP port')
    digest_parser.add_argument('--email-user', help='SMTP username')
    digest_parser.add_argument('--email-pass', help='SMTP password (app password)')
    digest_parser.add_argument('--from-email', help='From email address')
    digest_parser.add_argument('--to-email', help='To email address')

    # Slack args
    digest_parser.add_argument('--slack-webhook', help='Slack webhook URL')
    digest_parser.add_argument('--slack-channel', default='#general', help='Slack channel')

    # Telegram args
    digest_parser.add_argument('--telegram-token', help='Telegram bot token')
    digest_parser.add_argument('--telegram-chat', help='Telegram chat ID')

    # stats
    subparsers.add_parser('stats', help='Show database statistics')

    # sources
    sources_parser = subparsers.add_parser('sources', help='List configured sources')
    sources_parser.add_argument('--all', action='store_true', help='Show disabled sources too')

    # cleanup
    cleanup_parser = subparsers.add_parser('cleanup', help='Remove old entries')
    cleanup_parser.add_argument('--days', type=int, default=90, help='Delete entries older than N days (default: 90)')

    # analyze
    analyze_parser = subparsers.add_parser('analyze', help='Run AI analysis on unanalyzed entries')
    analyze_parser.add_argument('--since', help='ISO date to analyze from (default: 24h ago)')
    analyze_parser.add_argument('--limit', type=int, default=50, help='Max entries to analyze (default: 50)')

    # enriched-digest
    enriched_parser = subparsers.add_parser('enriched-digest', help='Generate and send AI-enriched digest')
    enriched_parser.add_argument('--schedule', choices=['daily', 'weekly'], default='daily',
                               help='Digest schedule (default: daily)')
    enriched_parser.add_argument('--method', choices=['console', 'email', 'slack', 'telegram'],
                               default='console', help='Delivery method (default: console)')
    enriched_parser.add_argument('--since', help='ISO date to analyze from (default: 24h ago)')
    enriched_parser.add_argument('--limit', type=int, default=50, help='Max entries to analyze (default: 50)')
    enriched_parser.add_argument('--max-items', type=int, default=10, help='Max items per category (default: 10)')

    # Email args
    enriched_parser.add_argument('--smtp-server', default='smtp.gmail.com', help='SMTP server')
    enriched_parser.add_argument('--smtp-port', type=int, default=587, help='SMTP port')
    enriched_parser.add_argument('--email-user', help='SMTP username')
    enriched_parser.add_argument('--email-pass', help='SMTP password (app password)')
    enriched_parser.add_argument('--from-email', help='From email address')
    enriched_parser.add_argument('--to-email', help='To email address')

    # Slack args
    enriched_parser.add_argument('--slack-webhook', help='Slack webhook URL')
    enriched_parser.add_argument('--slack-channel', default='#general', help='Slack channel')

    # Telegram args
    enriched_parser.add_argument('--telegram-token', help='Telegram bot token')
    enriched_parser.add_argument('--telegram-chat', help='Telegram chat ID')

    # newspaper / chronicle
    newspaper_parser = subparsers.add_parser('newspaper', help='Generate and dispatch 5-hour newspaper/newsletter edition')
    newspaper_parser.add_argument('--window-hours', type=int, default=5, help='Threat intelligence time window in hours (default: 5)')
    newspaper_parser.add_argument('--telegram', action='store_true', help='Dispatch PDF edition to Telegram')
    newspaper_parser.add_argument('--telegram-token', help='Telegram bot token')
    newspaper_parser.add_argument('--telegram-chat', help='Telegram chat ID')
    newspaper_parser.add_argument('--email', help='Recipient email address to dispatch PDF')
    newspaper_parser.add_argument('--smtp-server', help='SMTP server (default from config)')
    newspaper_parser.add_argument('--smtp-port', type=int, help='SMTP port (default from config)')
    newspaper_parser.add_argument('--email-user', help='SMTP username')
    newspaper_parser.add_argument('--email-pass', help='SMTP password')
    newspaper_parser.add_argument('--from-email', help='Sender email address')

    # test-delivery
    test_parser = subparsers.add_parser('test-delivery', help='Test delivery method')
    test_parser.add_argument('--method', choices=['console', 'email', 'slack', 'telegram'],
                             default='console', help='Delivery method to test')
    test_parser.add_argument('--smtp-server', default='smtp.gmail.com')
    test_parser.add_argument('--smtp-port', type=int, default=587)
    test_parser.add_argument('--email-user')
    test_parser.add_argument('--email-pass')
    test_parser.add_argument('--from-email')
    test_parser.add_argument('--to-email')
    test_parser.add_argument('--slack-webhook')
    test_parser.add_argument('--slack-channel', default='#general')
    test_parser.add_argument('--telegram-token')
    test_parser.add_argument('--telegram-chat')

    # strategy-init
    strategy_init_parser = subparsers.add_parser('strategy-init', help='Initialize strategy genome population')
    strategy_init_parser.add_argument('--population', type=int, default=20, help='Population size (default: 20)')
    strategy_init_parser.add_argument('--test-entries', type=int, default=50, help='Test entries for benchmark (default: 50)')
    strategy_init_parser.add_argument('--skip-benchmark', action='store_true', help='Skip initial benchmark')
    strategy_init_parser.add_argument('--strategy-name', default='best', help='Name for saved strategy (default: best)')

    # strategy-evolve
    strategy_evolve_parser = subparsers.add_parser('strategy-evolve', help='Evolve strategies through generations')
    strategy_evolve_parser.add_argument('--generations', type=int, default=5, help='Number of generations (default: 5)')
    strategy_evolve_parser.add_argument('--population', type=int, default=20, help='Population size (default: 20)')
    strategy_evolve_parser.add_argument('--test-entries', type=int, default=100, help='Test entries per generation (default: 100)')
    strategy_evolve_parser.add_argument('--strategy-name', default='best', help='Strategy name to load/save (default: best)')

    # strategy-show
    strategy_show_parser = subparsers.add_parser('strategy-show', help='Show current best strategy')
    strategy_show_parser.add_argument('--strategy-name', default='best', help='Strategy name (default: best)')

    # replay
    replay_parser = subparsers.add_parser('replay', help='Replay historical entries with mutated strategies')
    replay_parser.add_argument('--limit', type=int, default=100, help='Entries to replay (default: 100)')
    replay_parser.add_argument('--strategy-name', default='best', help='Base strategy name (default: best)')

    # beliefs
    subparsers.add_parser('beliefs', help='Show system epistemic beliefs')

    # opportunities
    subparsers.add_parser('opportunities', help='Show detected improvement opportunities')

    # validate-strategy
    validate_parser = subparsers.add_parser('validate-strategy', help='Validate strategy improvement via replay')
    validate_parser.add_argument('--strategy-name', default='best', help='Base strategy name (default: best)')
    validate_parser.add_argument('--test-entries', type=int, default=100, help='Test entries (default: 100)')
    validate_parser.add_argument('--min-improvement', type=float, default=0.05, help='Min improvement required (default: 0.05)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Ensure config exists
    if not Path(args.config).exists():
        print(f"Config file not found: {args.config}")
        print("Run 'python -m cli init' first to create default config")
        sys.exit(1)

    # Dispatch
    commands = {
        'server': cmd_server,
        'init': cmd_init,
        'fetch': cmd_fetch,
        'digest': cmd_digest,
        'newspaper': cmd_newspaper,
        'stats': cmd_stats,
        'sources': cmd_sources,
        'cleanup': cmd_cleanup,
        'test-delivery': cmd_test_delivery,
        'analyze': cmd_analyze,
        'enriched-digest': cmd_enriched_digest,
        'strategy-init': cmd_strategy_init,
        'strategy-evolve': cmd_strategy_evolve,
        'strategy-show': cmd_strategy_show,
        'replay': cmd_replay,
        'beliefs': cmd_beliefs,
        'opportunities': cmd_opportunities,
        'validate-strategy': cmd_validate_strategy,
    }

    commands[args.command](args)


if __name__ == '__main__':
    main()