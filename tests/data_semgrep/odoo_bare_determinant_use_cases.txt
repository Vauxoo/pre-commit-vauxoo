from odoo import fields, models


class Bad(models.Model):
    _name = "bad"

    # ruleid: odoo-bare-determinant-inverse
    a = fields.Char(inverse=_set_a)
    # ruleid: odoo-bare-determinant-search
    b = fields.Char(search=_search_b)
    # ruleid: odoo-bare-determinant-group_expand
    c = fields.Char(group_expand=_expand_c)
    # ruleid: odoo-bare-determinant-compute
    d = fields.Char(compute=_compute_d)

    # A field mixing the two forms is still reported on the bare one, which is why
    # there is one rule per keyword instead of one rule with a shared pattern-not
    # ruleid: odoo-bare-determinant-inverse
    h = fields.Char(compute="_compute_h", inverse=_set_h)

    # A reference reached through an attribute skips the MRO just the same
    # ruleid: odoo-bare-determinant-compute
    i = fields.Char(compute=helpers.compute_i)

    # ok: odoo-bare-determinant-inverse
    e = fields.Char(inverse="_set_e")
    # ok: odoo-bare-determinant-compute
    # ok: odoo-bare-determinant-search
    f = fields.Char(compute="_compute_f", search="_search_f")
    # ok: odoo-bare-determinant-group_expand
    g = fields.Char(group_expand=None)
    # ok: odoo-bare-determinant-compute
    j = fields.Char(compute=False)

    # True is the Odoo 19 sentinel for "use the ORM default", not a callable
    # ok: odoo-bare-determinant-group_expand
    k = fields.Selection(group_expand=True)
    # ok: odoo-bare-determinant-search
    m = fields.Char(search=True)

    # The MRO lookup happens inside the body of the lambda, on the record, so an
    # override of _compute_n is reached normally
    # ok: odoo-bare-determinant-compute
    n = fields.Char(compute=lambda records: records._compute_n())
    # ok: odoo-bare-determinant-inverse
    o = fields.Char(inverse=lambda records, value: records._set_o(value))
