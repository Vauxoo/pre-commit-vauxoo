{
    "name": "module_warnings1",
    "summary": """
        Short (1 phrase/line) summary of the module's purpose, used as
        subtitle on modules listing or apps.openerp.com""",
    "author": "Vauxoo,Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "website": "http://www.yourcompany.com",
    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    "category": "Uncategorized",
    "version": "15.0.1.0.0",
    # any module necessary for this one to work correctly
    "depends": ["base"],
    # always loaded
    "data": [
        # 'security/ir.model.access.csv',
        "views/views.xml",
    ],
    # only loaded in demonstration mode
    "demo": [
        "demo/demo.xml",
    ],
}
