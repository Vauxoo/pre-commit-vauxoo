# from odoo import models, fields, api


# class module_example1(models.Model):
#     _name = 'module_example1.module_example1'
#     _description = 'module_example1.module_example1'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         for record in self:
#             record.value2 = float(record.value) / 100
