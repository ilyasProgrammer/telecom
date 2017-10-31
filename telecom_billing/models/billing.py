# -*- coding: utf-8 -*-

import json
from lxml import etree
from datetime import datetime
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.tools import float_is_zero, float_compare
from odoo.tools.misc import formatLang

from odoo.exceptions import UserError, RedirectWarning, ValidationError

import odoo.addons.decimal_precision as dp
import logging

_logger = logging.getLogger(__name__)


class TelecomBilling(models.Model):
    _inherit = 'account.invoice'
    is_billing = fields.Boolean('Is billing', default=False)
    invoice_ref = fields.Char(string='Invoice ref')
    account_no = fields.Char(readonly=True)
    payment_method = fields.Selection([('cheque', 'Cheque'),
                                       ('direct', 'Direct Debit'),
                                       ('card', 'Card Payment'),
                                       ('bank', 'Bank Transfer'),
                                       ('paypal', 'PayPal'),
                                       ('cash', 'Cash')])
    _sql_constraints = [
        ('invoice_ref_unique', 'UNIQUE(invoice_ref)', 'A invoice_ref must be unique!'),
    ]


class TelecomBillingLine(models.Model):
    _inherit = 'account.invoice.line'
    default_code = fields.Char(related='product_id.default_code')
