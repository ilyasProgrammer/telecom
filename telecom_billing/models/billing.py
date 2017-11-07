# -*- coding: utf-8 -*-

from os.path import expanduser
import csv
from StringIO import StringIO
from datetime import datetime
from odoo import api, fields, models, _
import werkzeug
import cgi
import json
from odoo import http
from odoo.http import request
from odoo.addons.base_import.controllers.main import ImportController
from odoo.exceptions import Warning
from odoo.http import Response
import itertools
import operator
import logging

_logger = logging.getLogger('# ' + __name__)


class TelecomBilling(models.Model):
    _inherit = 'account.invoice'
    is_billing = fields.Boolean('Is billing', default=False)
    invoice_ref = fields.Char(string='Invoice ref')
    # account_no = fields.Char(related='partner_id.x_account_no')
    account_no = fields.Char()
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
    def import_billings(self, content):
        res = []
        imported_cnt = 0
        paid_cnt = 0
        invoice = self.env['account.invoice']
        payment = self.env['account.payment']
        payment_method_manual_in = self.env.ref("account.account_payment_method_manual_in")
        register_payments_model = self.env['account.register.payments']
        line_account = self.env['account.account'].search([('name', '=', 'Sales Tax Control Account')])
        account = self.env['account.account'].search([('name', '=', 'Debtors Control Account')])
        tax = self.env['account.tax'].search([('name', '=', 'S')])[0]
        journal = self.env['account.journal'].search([('code', '=', 'BNK1')])
        # filename = '/home/r/1.csv'
        errors = self.check_rows(content)
        if len(errors):
            return {'errors': errors, 'imported_cnt': imported_cnt, 'paid_cnt': paid_cnt}
        spamreader = csv.reader(StringIO(content), delimiter=',', quotechar='"')
        for ind, row in enumerate(spamreader):
            if ind == 0:
                continue
            partner_name = row[1].strip()
            partner = self.env['res.partner'].search([('name', '=', partner_name)])
            product = self.env['product.product'].search([('name', '=', 'Electricity Bill')])
            # date = datetime.strptime(row[10].strip(), '%d.%m.%y')
            date = fields.Datetime.now()
            vals = {'partner_id': partner.id,
                    'invoice_ref': row[0].strip(),
                    'payment_method': row[3].strip(),
                    'account_id': account.id,
                    'name': row[9].strip(),
                    'date_invoice': date,
                    'is_billing': True,
                    }
            found = invoice.search([('invoice_ref', '=', row[0].strip())], limit=1)
            if len(found):
                msg = "Found existing old billing records: %s" % found.invoice_ref
                _logger.info(msg)
                if not int(row[10]) or found.state == 'paid':
                    msg = "Old invoice not intended to proceed payment and skipped: %s" % found.invoice_ref
                    _logger.info(msg)
                    continue
                else:
                    new_invoice = found
                    _logger.info("Old invoice going to be paid: %s", row[0].strip())
            else:
                new_invoice = invoice.create(vals)
                imported_cnt += 1
                _logger.info("New invoice created: %s", row[0].strip())
                amount = float(row[6].strip())
                line_vals = {'product_id': product.id,
                             'account_id': line_account.id,
                             'price_unit': amount,
                             'name': 'imported',
                             'partner_id': partner.id,
                             'invoice_line_tax_ids': [(6, 0, [tax.id])],
                             }
                new_invoice.write({'invoice_line_ids': [(0, 0, line_vals)]})
                new_invoice.compute_taxes()
            # Register payment
            if int(row[10]):
                new_invoice.action_invoice_open()
                _logger.info("Validated invoice: %s", new_invoice.invoice_ref)
                ctx = {'active_model': 'account.invoice', 'active_ids': [new_invoice.id]}
                register_payments = register_payments_model.with_context(ctx).create({
                    'payment_date': date,
                    'journal_id': journal.id,
                    'payment_method_id': payment_method_manual_in.id,
                })
                register_payments.create_payment()
                _logger.info("Payment registered for invoice: %s", new_invoice.invoice_ref)
                payments = payment.search([], order="id desc", limit=1)
                liquidity_aml = payments.move_line_ids.filtered(lambda r: r.user_type_id.type == 'liquidity')
                bank_statement = self.reconcile(liquidity_aml, date, partner, liquidity_aml.debit, 0, False)
                _logger.info("Bank statement registered for invoice: %s", new_invoice.invoice_ref)
                paid_cnt += 1
        return {'errors': res, 'imported_cnt': imported_cnt, 'paid_cnt': paid_cnt}

    def check_rows(self, rows):
        r1 = csv.reader(StringIO(rows), delimiter=',', quotechar='"')
        res = []
        ref_numbers = set()
        duplicated_refs = []
        for row in r1:
            if row[0] not in ref_numbers:
                ref_numbers.add(row[0])
            else:
                duplicated_refs.append(row[0])
        if len(duplicated_refs):
            res.append('duplicated refs:' + str(duplicated_refs))
        invoice = self.env['account.invoice']
        r2 = csv.reader(StringIO(rows), delimiter=',', quotechar='"')
        for ind, row in enumerate(r2):
            if ind == 0:
                continue
            # found = invoice.search([('invoice_ref', '=', row[0].strip())], limit=1)
            # if len(found):
            #     msg = "Found existing old billing records: %s" % found.invoice_ref
            #     _logger.error(msg)
            #     res.append(msg)
            #     return res
            partner_name = row[1].strip()
            partner = self.env['res.partner'].search([('name', '=', partner_name)])
            if not partner:
                msg = "Partner not found: %s" % partner_name
                _logger.error(msg)
                res.append(msg)
                return res
            if len(partner) > 1:
                msg = "More than one partner with same name: %s" % partner_name
                _logger.error(msg)
                res.append(msg)
                return res
            product = self.env['product.product'].search([('name', '=', 'Electricity Bill')])
            if not product:
                msg = "Product not found: %s" % 'Electricity Bill'
                _logger.error(msg)
                res.append(msg)
                return res
        return res

    def reconcile(self, liquidity_aml, date, partner, amount=0.0, amount_currency=0.0, currency_id=None):
        """ Reconcile a journal entry corresponding to a payment with its bank statement line """
        acc_bank_stmt_model = self.env['account.bank.statement']
        acc_bank_stmt_line_model = self.env['account.bank.statement.line']
        bank_stmt = acc_bank_stmt_model.create({
            'journal_id': liquidity_aml.journal_id.id,
            'date': date,
        })
        bank_stmt_line = acc_bank_stmt_line_model.create({
            'name': 'payment',
            'statement_id': bank_stmt.id,
            'partner_id': partner.id,
            'amount': amount,
            'amount_currency': amount_currency,
            'currency_id': currency_id,
            'date': date
        })

        amount_in_widget = currency_id and amount_currency or amount
        bank_stmt_line.process_reconciliation(payment_aml_rec=liquidity_aml)
        return bank_stmt


class TelecomBillingLine(models.Model):
    _inherit = 'account.invoice.line'
    default_code = fields.Char(related='product_id.default_code')


class Extension(models.TransientModel):
    _inherit = 'base_import.import'

    @api.multi
    def parse_preview(self, options, count=10):
        report = ''
        if self.res_model != 'account.invoice':
            return super(Extension, self).parse_preview(options, count)
        res = self.env['account.invoice'].search([])[0].import_billings(self.file)[0]
        if len(res['errors']) == 0:
            report += "Everything ok \n"
            report += "Imported invoices: %s \n" % res['imported_cnt']
            report += "Payment registered for: %s \n" % res['paid_cnt']
        else:
            report = res['errors']
        return {
            'error': str('Import data error. Process interrupted.'),
            'preview': report,
        }