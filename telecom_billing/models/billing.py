# -*- coding: utf-8 -*-

import csv
from StringIO import StringIO
from datetime import datetime
from odoo import api, fields, models, _
import logging

_logger = logging.getLogger('# ' + __name__)
PRODUCT_NAME = 'Monthly Telecom & Data Bill'


class TelecomBilling(models.Model):
    _inherit = 'account.invoice'
    is_billing = fields.Boolean('Is billing', default=False)
    invoice_ref = fields.Char(string='Invoice ref')
    account_no = fields.Char(related='partner_id.x_account_no')
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
    def import_register_payments(self, content):
        paid_cnt = 0
        invoice_model = self.env['account.invoice']
        partner_model = self.env['res.partner']
        payment_model = self.env['account.payment']
        journal_id = self.env['account.journal'].search([('code', '=', 'BNK1')])
        payment_method_manual_in = self.env.ref("account.account_payment_method_manual_in")
        register_payments_model = self.env['account.register.payments']
        reader = csv.DictReader(StringIO(content), delimiter=',', quotechar='"')
        for row in reader:
            partner_id = partner_model.search([('is_company', '=', True), ('x_account_no', '=', row['Account Number'])])
            invoice_ids = invoice_model.search([('partner_id', '=', partner_id.id), ('state', '=', 'open')])
            date = datetime.strptime(row['Date'].strip(), '%d/%m/%Y')
            for inv in invoice_ids:
                inv.date_invoice = date  # set payment date
                # invoice_ids.action_invoice_open()
                # _logger.info("Validated invoice: %s", inv.invoice_ref)
            ctx = {'active_model': 'account.invoice', 'active_ids': invoice_ids.ids}
            register_payments = register_payments_model.with_context(ctx).create({
                'payment_date': date,
                'journal_id': journal_id.id,
                'payment_method_id': payment_method_manual_in.id,
                'amount': float(row['Total']),
            })
            register_payments.create_payment()
            _logger.info("Payment registered for partner %s invoices: %s" % (partner_id.name, invoice_ids.ids))
            # payments = payment_model.search([], order="id desc", limit=1)
            # liquidity_aml = payments.move_line_ids.filtered(lambda r: r.user_type_id.type == 'liquidity')
            # bank_statement = self.reconcile(liquidity_aml, date, partner_id, liquidity_aml.debit, 0, False)
            # _logger.info("Bank statement registered for invoices: %s", invoice_ids.ids)
            paid_cnt += 1
        return paid_cnt

    @api.one
    def import_billings(self, content):
        imported_cnt = 0
        invoice = self.env['account.invoice']
        line_account = self.env['account.account'].search([('name', '=', 'Sales Tax Control Account')])
        account = self.env['account.account'].search([('name', '=', 'Debtors Control Account')])
        product = self.env['product.product'].search([('name', '=', PRODUCT_NAME)])
        tax = self.env['account.tax'].search([('name', '=', 'S')])[0]
        reader = csv.DictReader(StringIO(content), delimiter=',', quotechar='"')
        for ind, row in enumerate(reader):
            partner_name = row['Site Name'].strip()
            partner = self.env['res.partner'].search([('is_company', '=', True), ('name', '=', partner_name)])
            date = fields.Datetime.now()
            vals = {'partner_id': partner.id,
                    'invoice_ref': row['Invoice Number'].strip(),
                    'payment_method': row['Payment Method'].strip(),
                    'account_id': account.id,
                    'name': row['Period'].strip(),
                    'date_invoice': date,
                    'is_billing': True,
                    }
            new_invoice = invoice.create(vals)
            imported_cnt += 1
            _logger.info("New invoice created: %s", row['Invoice Number'].strip())
            amount = float(row['Service Charges'].strip())
            line_vals = {'product_id': product.id,
                         'account_id': line_account.id,
                         'price_unit': amount,
                         'name': 'imported',
                         'partner_id': partner.id,
                         'invoice_line_tax_ids': [(6, 0, [tax.id])],
                         }
            new_invoice.write({'invoice_line_ids': [(0, 0, line_vals)]})
            new_invoice.compute_taxes()

    @api.one
    def import_file(self, content):
        errors = []
        imported_cnt = 0
        paid_cnt = 0
        reader = csv.DictReader(StringIO(content), delimiter=',', quotechar='"')
        ln = len(reader.fieldnames)
        if ln == 4:  # importing file for payment register
            errors = self.check_payments_rows(content)
            if len(errors) == 0:
                paid_cnt = self.import_register_payments(content)
        elif ln == 10:  # importing billings without payments
            errors = self.check_import_rows(content)
            if len(errors) == 0:
                imported_cnt = self.import_billings(content)
        else:
            errors.append('Wrong amount of columns in file. Expected 4 or 10. Got %s' % ln)
        return {'errors': errors, 'imported_cnt': imported_cnt, 'paid_cnt': paid_cnt}

    def check_import_rows(self, content):
        res = []
        ref_numbers = set()
        duplicated_refs = []
        invoice_model = self.env['account.invoice']
        reader = csv.DictReader(StringIO(content), delimiter=',', quotechar='"')
        for row in reader:
            if row['Invoice Number'] not in ref_numbers:
                ref_numbers.add(row['Invoice Number'])
            else:
                duplicated_refs.append(row['Invoice Number'])
        if len(duplicated_refs):
            res.append('duplicated refs:' + str(duplicated_refs))
        reader = csv.DictReader(StringIO(content), delimiter=',', quotechar='"')
        for ind, row in enumerate(reader):
            found = invoice_model.search([('invoice_ref', '=', row['Invoice Number'].strip())], limit=1)
            if len(found):
                msg = "Found existing old billing records: %s" % found.invoice_ref
                _logger.error(msg)
                res.append(msg)
                return res
            partner_name = row['Site Name'].strip()
            partner = self.env['res.partner'].search([('is_company', '=', True), ('name', '=', partner_name)])
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
            product = self.env['product.product'].search([('name', '=', PRODUCT_NAME)])
            if not product:
                msg = "Product not found: %s" % PRODUCT_NAME
                _logger.error(msg)
                res.append(msg)
                return res
        return res

    def check_payments_rows(self, content):
        res = []
        ref_numbers = set()
        duplicated_refs = []
        invoice_model = self.env['account.invoice']
        reader = csv.DictReader(StringIO(content), delimiter=',', quotechar='"')
        for row in reader:
            if row['Account Number'] not in ref_numbers:
                ref_numbers.add(row['Account Number'])
            else:
                duplicated_refs.append(row['Account Number'])
        if len(duplicated_refs):
            res.append('Duplicated Account Number:' + str(duplicated_refs) + '\n')
        reader = csv.DictReader(StringIO(content), delimiter=',', quotechar='"')
        for ind, row in enumerate(reader):
            if not len(row['Account Number']):
                msg = "Line %s. Empty Account Number in row: %s" % row
                _logger.error(msg)
                res.append(msg)
                return res
            x_account_no = row['Account Number'].strip()
            partner = self.env['res.partner'].search([('is_company', '=', True), ('x_account_no', '=', x_account_no)])
            if not partner:
                msg = "Line %s. Partner not found: %s \n" % (ind, x_account_no)
                _logger.error(msg)
                res.append(msg)
                return res
            if len(partner) > 1:
                msg = "Line %s. More than one partner with same x_account_no: %s \n" % (ind, x_account_no)
                _logger.error(msg)
                res.append(msg)
                return res
            invoice_ids = invoice_model.search([('partner_id', '=', partner.id), ('state', '=', 'open')])
            if len(invoice_ids) == 0:
                msg = "Line %s. There is no open invoices for partner %s \n" % (ind, partner.name)
                _logger.error(msg)
                res.append(msg)
                return res
            product = self.env['product.product'].search([('name', '=', PRODUCT_NAME)])
            if not product:
                msg = "Line %s. Product not found: %s \n" % (ind, PRODUCT_NAME)
                _logger.error(msg)
                res.append(msg)
                return res
            if len(row['Total']):
                if float(row['Total']) <= 0:
                    msg = "Line %s. Total is less that 0 for x_account_no: %s \n" % (ind, x_account_no)
                    _logger.error(msg)
                    res.append(msg)
                    return res
            else:
                msg = "Line %s. Total is absent for x_account_no: %s \n" % (ind, x_account_no)
                _logger.error(msg)
                res.append(msg)
                return res
            if len(row['Date']):
                try:
                    date = datetime.strptime(row['Date'].strip(), '%d/%m/%Y')
                except:
                    msg = "Line %s. Wrong date format: %s \n" % (ind, row['Date'])
                    _logger.info(msg)
            else:
                msg = "Line %s. Date is absent. \n" % ind
                _logger.error(msg)
                res.append(msg)
                return res
            if len(row['Paid']):
                if row['Paid'] != 'Success':
                    msg = "Line %s. No Success. \n" % ind
                    _logger.info(msg)
            else:
                msg = "Line %s. Empty Paid field. \n" % ind
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
        res = self.env['account.invoice'].search([])[0].import_file(self.file)[0]
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