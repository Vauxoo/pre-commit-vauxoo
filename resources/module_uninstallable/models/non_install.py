from odoo import models


class NonInstall(models.model):
    _name = "non.install"

    def please_hack_me(self, payload):
        # Trigger a pylint possible sql injection error.
        self.env.cr.execute("SELECT * FROM table_in_danger WHERE id = %s" % payload)
