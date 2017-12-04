# -*- coding: utf-8 -*-

{
    'name': 'Telecom Billing',
    'version': '1.1',
    'category': 'custom',
    'sequence': 200,
    'summary': 'Read requirements.txt please',
    'description': """
    """,
    'website': 'https://www.odoo.com/page/employees',
    'images': [
    ],
    'depends': [
        'sale',
        'account',
    ],
    'external_dependencies': {"python": ['Tkinter']},
    'data': [
        'views/views.xml',
        'cron.xml'
    ],
    "init_xml": ["init.xml"],
    'demo': [
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'qweb': [],
}
