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

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from monitor import AISecurityMonitor, run_fetch_job, run_digest_job


def cmd_analyze(args):
    """Run AI analysis on unanalyzed entries."""
    print(f"Running AI analysis on recent entries...")
    monitor = AISecurityMonitor(args.config)
    results = monitor.run_analysis(since=args.since, limit=args.limit)
    print(f"\nResults:")
    print(f"  Analyzed: {results['analyzed']}")
    print(f"  Failed:   {results['failed']}")
    print(f"  High Velocity (>=70): {results['high_velocity']}")


def cmd_enriched_digest(args):
    """Generate and send AI-enriched digest."""
    print(f"Generating {args.schedule} enriched digest via {args.method}...")

    monitor = AISecurityMonitor(args.config)

    # First run analysis to enrich entries
    print("Running AI analysis to enrich digest...")
    monitor.run_analysis(since=args.since, limit=args.limit)

    # Then generate enriched digest
    digest = monitor.generate_enriched_digest(since=args.since, max_per_category=args.max_items)

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
        'stats': cmd_stats,
        'sources': cmd_sources,
        'cleanup': cmd_cleanup,
        'test-delivery': cmd_test_delivery,
        'analyze': cmd_analyze,
        'enriched-digest': cmd_enriched_digest,
    }

    commands[args.command](args)


if __name__ == '__main__':
    main()