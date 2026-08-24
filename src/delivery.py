"""
Delivery modules for sending digests via various channels.
Supports Email, Slack, Telegram, and Console output.
"""

import logging
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

logger = logging.getLogger(__name__)


class BaseDelivery:
    """Base class for delivery methods."""

    def __init__(self, config: dict):
        self.config = config

    def send(self, subject: str, content: str, entries_by_category: dict) -> bool:
        """Send the digest. Returns True on success."""
        raise NotImplementedError


class ConsoleDelivery(BaseDelivery):
    """Print digest to console (always available as fallback)."""

    def send(self, subject: str, content: str, entries_by_category: dict) -> bool:
        print("\n" + "=" * 80)
        print(f" {subject}")
        print("=" * 80)
        print(content)
        print("=" * 80 + "\n")
        return True


class EmailDelivery(BaseDelivery):
    """Send digest via email using SMTP."""

    def send(self, subject: str, content: str, entries_by_category: dict) -> bool:
        smtp_server = self.config.get('smtp_server', 'smtp.gmail.com')
        smtp_port = self.config.get('smtp_port', 587)
        username = self.config.get('username')
        password = self.config.get('password')  # App password
        from_email = self.config.get('from_email', username)
        to_email = self.config.get('to_email')

        if not all([username, password, to_email]):
            logger.error("Email config incomplete: need username, password, to_email")
            return False

        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = from_email
            msg['To'] = to_email

            # Plain text version
            text_part = MIMEText(content, 'plain', 'utf-8')
            msg.attach(text_part)

            # HTML version
            html_content = self._to_html(subject, content, entries_by_category)
            html_part = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(html_part)

            # Send
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)

            logger.info(f"Email sent to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def _to_html(self, subject: str, content: str, entries_by_category: dict) -> str:
        """Convert digest to HTML."""
        category_labels = {
            'ai_tech': '🤖 AI Technology Launches',
            'ai_research': '📚 AI Research Papers',
            'cybersecurity': '🔒 Cybersecurity News',
            'vulnerabilities': '⚠️ Vulnerabilities & CVEs',
            'github_trending': '⭐ GitHub Trending Security',
        }

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; }}
                h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
                h2 {{ color: #34495e; border-left: 4px solid #3498db; padding-left: 12px; margin-top: 30px; }}
                .entry {{ margin-bottom: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px; border-left: 3px solid #3498db; }}
                .entry-title {{ font-weight: 600; color: #2c3e50; margin-bottom: 8px; }}
                .entry-title a {{ color: #2c3e50; text-decoration: none; }}
                .entry-title a:hover {{ color: #3498db; }}
                .entry-meta {{ font-size: 0.85em; color: #7f8c8d; margin-bottom: 8px; }}
                .entry-summary {{ color: #555; }}
                .source-tag {{ display: inline-block; background: #e1e8ed; color: #555; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; margin-right: 6px; }}
                .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #eee; color: #999; font-size: 0.85em; text-align: center; }}
            </style>
        </head>
        <body>
            <h1>{subject}</h1>
        """

        for cat, entries in entries_by_category.items():
            if not entries:
                continue
            label = category_labels.get(cat, cat.replace('_', ' ').title())
            html += f"<h2>{label} ({len(entries)})</h2>"

            for entry in entries:
                source = entry.get('source_name', '')
                pub_date = entry.get('published_at', '')
                if isinstance(pub_date, datetime):
                    pub_date = pub_date.strftime('%Y-%m-%d %H:%M')
                elif isinstance(pub_date, str):
                    pub_date = pub_date[:16]

                tags_html = ''
                for tag in entry.get('tags', [])[:5]:
                    tags_html += f'<span class="source-tag">{tag}</span>'

                html += f"""
                <div class="entry">
                    <div class="entry-title"><a href="{entry['url']}">{entry['title']}</a></div>
                    <div class="entry-meta">
                        <span class="source-tag">{source}</span>
                        {f'<span>{pub_date}</span>' if pub_date else ''}
                        {tags_html}
                    </div>
                    <div class="entry-summary">{entry.get('summary', '')}</div>
                </div>
                """

        html += f"""
            <div class="footer">
                Generated by AI Security Monitor · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
        </body>
        </html>
        """
        return html


class SlackDelivery(BaseDelivery):
    """Send digest via Slack webhook."""

    def send(self, subject: str, content: str, entries_by_category: dict) -> bool:
        webhook_url = self.config.get('webhook_url')
        channel = self.config.get('channel', '#general')

        if not webhook_url:
            logger.error("Slack webhook_url not configured")
            return False

        try:
            # Build Slack blocks
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": subject}},
                {"type": "divider"}
            ]

            category_labels = {
                'ai_tech': '🤖 AI Technology Launches',
                'ai_research': '📚 AI Research Papers',
                'cybersecurity': '🔒 Cybersecurity News',
                'vulnerabilities': '⚠️ Vulnerabilities & CVEs',
                'github_trending': '⭐ GitHub Trending Security',
            }

            for cat, entries in entries_by_category.items():
                if not entries:
                    continue

                label = category_labels.get(cat, cat.replace('_', ' ').title())
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{label}* ({len(entries)} items)"}
                })

                for entry in entries[:5]:  # Limit per category for Slack
                    source = entry.get('source_name', '')
                    title = entry['title']
                    url = entry['url']
                    summary = entry.get('summary', '')[:200]

                    text = f"*<{url}|{title}>*\n_{source}_\n{summary}"
                    blocks.append({
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": text}
                    })

                blocks.append({"type": "divider"})

            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Generated by AI Security Monitor · {datetime.now().strftime('%Y-%m-%d %H:%M')}"}]
            })

            payload = {
                "channel": channel,
                "blocks": blocks,
                "text": subject  # Fallback
            }

            response = requests.post(webhook_url, json=payload, timeout=15)
            response.raise_for_status()

            logger.info(f"Slack message sent to {channel}")
            return True

        except Exception as e:
            logger.error(f"Failed to send Slack message: {e}")
            return False


class TelegramDelivery(BaseDelivery):
    """Send digest via Telegram Bot API."""

    def send(self, subject: str, content: str, entries_by_category: dict) -> bool:
        bot_token = self.config.get('bot_token')
        chat_id = self.config.get('chat_id')

        if not bot_token or not chat_id:
            logger.error("Telegram config incomplete: need bot_token and chat_id")
            return False

        try:
            # Telegram has 4096 char limit per message, so we split
            category_labels = {
                'ai_tech': '🤖 AI Technology Launches',
                'ai_research': '📚 AI Research Papers',
                'cybersecurity': '🔒 Cybersecurity News',
                'vulnerabilities': '⚠️ Vulnerabilities & CVEs',
                'github_trending': '⭐ GitHub Trending Security',
            }

            # Send header
            header = f"<b>{subject}</b>\n\n"
            self._send_message(bot_token, chat_id, header)

            for cat, entries in entries_by_category.items():
                if not entries:
                    continue

                label = category_labels.get(cat, cat.replace('_', ' ').title())
                cat_header = f"\n<b>{label}</b> ({len(entries)} items)\n"
                self._send_message(bot_token, chat_id, cat_header)

                for entry in entries[:5]:  # Limit per category
                    source = entry.get('source_name', '')
                    title = entry['title']
                    url = entry['url']
                    summary = entry.get('summary', '')[:200]

                    msg = f"<b><a href='{url}'>{title}</a></b>\n<code>{source}</code>\n{summary}\n"
                    self._send_message(bot_token, chat_id, msg)

            footer = f"\n<i>Generated by AI Security Monitor · {datetime.now().strftime('%Y-%m-%d %H:%M')}</i>"
            self._send_message(bot_token, chat_id, footer)

            logger.info(f"Telegram messages sent to {chat_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    def _send_message(self, bot_token: str, chat_id: str, text: str) -> bool:
        """Send a single message to Telegram."""
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return True


def get_delivery(method: str, config: dict) -> BaseDelivery:
    """Get delivery instance by method name."""
    deliveries = {
        'console': ConsoleDelivery,
        'email': EmailDelivery,
        'slack': SlackDelivery,
        'telegram': TelegramDelivery,
    }
    cls = deliveries.get(method)
    if not cls:
        raise ValueError(f"Unknown delivery method: {method}")
    return cls(config)
