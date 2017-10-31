# -*- coding: utf-8 -*-

from os.path import expanduser
import csv
from StringIO import StringIO
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


class TelecomBillingLine(models.Model):
    _inherit = 'account.invoice.line'
    default_code = fields.Char(related='product_id.default_code')


class AttachementMode(models.Model):
    _inherit = 'ir.attachment'

    @api.one
    def import_billings(self):
        invoice = self.env['account.invoice']
        payment = self.env['account.payment']
        payment_method_manual_in = self.env.ref("account.account_payment_method_manual_in")
        register_payments_model = self.env['account.register.payments']
        line_account = self.env['account.account'].search([('name', '=', 'Sales Tax Control Account')])
        account = self.env['account.account'].search([('name', '=', 'Debtors Control Account')])
        tax = self.env['account.tax'].search([('name', '=', 'S')])[0]
        journal = self.env['account.journal'].search([('code', '=', 'BNK1')])
        content = self.index_content
        # filename = '/home/r/1.csv'
        spamreader = csv.reader(StringIO(content), delimiter=',', quotechar='"')
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
            date = datetime.strptime(row[10].strip(), '%d.%m.%y')
            vals = {'partner_id': partner.id,
                    'invoice_ref': row[0].strip(),
                    'payment_method': row[3].strip(),
                    'account_id': account.id,
                    'name': row[9].strip(),
                    'date_invoice': date,
                    'is_billing': True,
                    }
            new_invoice = invoice.create(vals)
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
            if int(row[11]):
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
