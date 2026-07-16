"""warning docstring-first-line-empty
"""

from odoo import fields, models


class AccountAnalyticLine(models.Model):
    _inherit = "account.analytic.line"

    deadline = fields.Date(help="The longest task related to this card will define the deadline.", tracking=True)
