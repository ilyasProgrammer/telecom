# -*- coding: utf-8 -*-

from os.path import expanduser
import csv
from Tkinter import Tk
from tkFileDialog import askopenfilename
from datetime import datetime
from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class TelecomBilling(models.Model):
    _inherit = 'account.invoice'
    is_billing = fields.Boolean('Is billing', default=False)
    invoice_ref = fields.Char(string='Invoice ref')
    account_no = fields.Char(readonly=True)
    payment_method = fields.Selection([('Cheque', 'Cheque'),
                                       ('Direct Debit', 'Direct Debit'),
                                       ('Card Payment', 'Card Payment'),
                                       ('Bank Transfer', 'Bank Transfer'),
                                       ('PayPal', 'PayPal'),
                                       ('Cash', 'Cash')])
    _sql_constraints = [
        ('invoice_ref_unique', 'UNIQUE(invoice_ref)', 'A invoice_ref must be unique!'),
    ]

    @api.one
    def import_billings(self):
        root = Tk()
        root.withdraw()
        home = expanduser("~")
        invoice = self.env['account.invoice']
        line_account = self.env['account.account'].search([('name', '=', 'Sales Tax Control Account')])
        account = self.env['account.account'].search([('name', '=', 'Debtors Control Account')])
        tax = self.env['account.tax'].search([('name', '=', 'S')])
        filename = '/home/r/1.csv'
        # filename = askopenfilename(initialdir=home)
        # root.destroy()
        with open(filename, 'rb') as csvfile:
            spamreader = csv.reader(csvfile, delimiter=',', quotechar='"')
            for ind, row in enumerate(spamreader):
                if ind == 0:
                    continue
                found = invoice.search([('invoice_ref', '=', row[0].strip())], limit=1)
                if len(found):
                    _logger.error("Found existing old billing records: %s", found.invoice_ref)
                    continue
                partner_name = row[1].strip()
                partner = self.env['res.partner'].search([('name', '=', partner_name)])
                if not partner:
                    _logger.error("Partner not found: %s", partner_name)
                    continue
                if len(partner) > 1:
                    _logger.error("More than one partner with same name: %s", partner_name)
                    continue
                product = self.env['product.product'].search([('name', '=', 'Electricity Bill')])
                if not product:
                    _logger.error("Product not found: %s", 'Electricity Bill')
                    continue

                vals = {'partner_id': partner.id,
                        'invoice_ref': row[0].strip(),
                        'payment_method': row[3].strip(),
                        'account_id': account.id,
                        'name': row[9].strip(),
                        'date_invoice': datetime.strptime(row[10].strip(), '%d.%m.%y'),
                        'is_billing': True,
                        }
                new_invoice = invoice.create(vals)
                _logger.info("New invoice created: %s", row[0].strip())
                line_vals = {'product_id': product.id,
                             'account_id': line_account.id,
                             'price_unit': float(row[5].strip()) - float(row[4].strip()),
                             'name': 'imported',
                             'partner_id': partner.id,
                             'invoice_line_tax_ids': [(6, 0, [tax.id])],
                             }
                new_invoice.write({'invoice_line_ids': [(0, 0, line_vals)]})
                new_invoice.compute_taxes()


class TelecomBillingLine(models.Model):
    _inherit = 'account.invoice.line'
    default_code = fields.Char(related='product_id.default_code')
