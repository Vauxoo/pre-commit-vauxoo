from markupsafe import Markup

from odoo.tools import html_sanitize


def body2markup(body):
    """Build a HTML body for 'message_post' without raising bandit B704

    Markup() is mandatory since 'message_post' escapes anything that is not a
    Markup object, so the value is sanitized instead of escaped
    """
    return Markup(html_sanitize(body))
