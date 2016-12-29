# -*- coding: utf-8 -*-
# Copyright 2012, Israel Cruz Argil, Argil Consulting
# Copyright 2016, Jarsa Sistemas, S.A. de C.V.
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from openerp import _, api, exceptions, fields, models


class TmsAdvance(models.Model):
    _name = 'tms.advance'
    _inherit = ['mail.thread', 'ir.needaction_mixin']
    _description = 'Money advance payments for Travel expenses'
    _order = "name desc, date desc"

    operating_unit_id = fields.Many2one(
        'operating.unit', string='Operating Unit', required=True)
    name = fields.Char(string='Advance Number')
    state = fields.Selection(
        [('draft', 'Draft'),
         ('approved', 'Approved'),
         ('confirmed', 'Confirmed'),
         ('closed', 'Closed'),
         ('cancel', 'Cancelled')],
        string='State',
        readonly=True,
        default='draft')
    date = fields.Date(
        'Date',
        required=True,
        default=fields.Date.today)
    travel_id = fields.Many2one(
        'tms.travel',
        string='Travel')
    unit_id = fields.Many2one(
        'fleet.vehicle',
        string='Unit')
    employee_id = fields.Many2one(
        'hr.employee',
        string='Driver')
    amount = fields.Monetary(required=True)
    notes = fields.Text()
    move_id = fields.Many2one(
        'account.move', 'Journal Entry',
        help="Link to the automatically generated Journal Items.\nThis move "
        "is only for Travel Expense Records with balance < 0.0",
        readonly=True)
    paid = fields.Boolean(
        compute='_compute_paid',
        readonly=True)
    payment_id = fields.Many2one(
        'account.payment',
        string="Payment Reference",
        readonly=True)
    currency_id = fields.Many2one(
        'res.currency',
        'Currency',
        required=True,
        default=lambda self: self.env.user.company_id.currency_id)
    auto_expense = fields.Boolean(
        help="Check this if you want this product and amount to be "
        "automatically created when Travel Expense Record is created.")
    expense_id = fields.Many2one(
        'tms.expense', 'Expense Record', readonly=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain=[('tms_product_category', '=', 'real_expense')])

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Advance number must be unique !'),
    ]

    @api.model
    def create(self, values):
        advance = super(TmsAdvance, self).create(values)
        sequence = advance.operating_unit_id.advance_sequence_id
        if advance.amount <= 0:
            raise exceptions.ValidationError(
                _('The amount must be greater than zero.'))
        else:
            advance.name = sequence.next_by_id()
            if advance.name == 'False':
                raise exceptions.ValidationError(
                    _('Error you need define an'
                        ' advance sequence in the base.'))
            else:
                return advance

    @api.multi
    def _compute_paid(self):
        for advance in self:
            if advance.payment_id.id:
                advance.paid = True

    @api.multi
    def action_approve(self):
        self.state = 'approved'
        self.message_post(_(
            '<strong>Advance approved.</strong><ul>'
            '<li><strong>Approved by: </strong>%s</li>'
            '<li><strong>Approved at: </strong>%s</li>'
            '</ul>') % (self.env.user.name, fields.Datetime.now()))

    @api.multi
    def action_confirm(self):
        for advance in self:
            if advance.amount <= 0:
                raise exceptions.ValidationError(
                    _('The amount must be greater than zero.'))
            else:
                obj_account_move = self.env['account.move']
                advance_journal_id = (
                    advance.operating_unit_id.advance_journal_id.id)
                advance_debit_account_id = (
                    advance.employee_id.
                    tms_advance_account_id.id
                )
                advance_credit_account_id = (
                    advance.employee_id.
                    address_home_id.property_account_payable_id.id
                )
                if not advance_journal_id:
                    raise exceptions.ValidationError(
                        _('Warning! The advance does not have a journal'
                          ' assigned. \nCheck if you already set the '
                          'journal for advances in the base.'))
                if not advance_credit_account_id:
                    raise exceptions.ValidationError(
                        _('Warning! The driver does not have a home address'
                          ' assigned. \nCheck if you already set the '
                          'home address for the employee.'))
                if not advance_debit_account_id:
                    raise exceptions.ValidationError(
                        _('Warning! You must have configured the accounts '
                            'of the tms'))
                move_lines = []
                notes = _('* Base: %s \n'
                          '* Advance: %s \n'
                          '* Travel: %s \n'
                          '* Driver: %s \n'
                          '* Vehicle: %s') % (
                    advance.operating_unit_id.name,
                    advance.name,
                    advance.travel_id.name,
                    advance.employee_id.name,
                    advance.unit_id.name)
                total = advance.currency_id.compute(
                    advance.amount,
                    self.env.user.currency_id)
                if total > 0.0:
                    accounts = {'credit': advance_credit_account_id,
                                'debit': advance_debit_account_id}
                    for name, account in accounts.items():
                        move_line = (0, 0, {
                            'name': advance.name,
                            'account_id': account,
                            'narration': notes,
                            'debit': (total if name == 'debit' else 0.0),
                            'credit': (total if name == 'credit' else 0.0),
                            'journal_id': advance_journal_id,
                            'operating_unit_id': advance.operating_unit_id.id,
                        })
                        move_lines.append(move_line)
                    move = {
                        'date': fields.Date.today(),
                        'journal_id': advance_journal_id,
                        'name': _('Advance: %s') % (advance.name),
                        'line_ids': [line for line in move_lines],
                        'operating_unit_id': advance.operating_unit_id.id
                    }
                    move_id = obj_account_move.create(move)
                    if not move_id:
                        raise exceptions.ValidationError(
                            _('An error has occurred in the creation'
                                ' of the accounting move. '))
                    else:
                        self.write(
                            {
                                'move_id': move_id.id,
                                'state': 'confirmed'
                            })
                        self.message_post(_(
                            '<strong>Advance confirmed.</strong><ul>'
                            '<li><strong>Confirmed by: </strong>%s</li>'
                            '<li><strong>Confirmed at: </strong>%s</li>'
                            '</ul>') % (self.env.user.name,
                                        fields.Datetime.now()))

    @api.multi
    def action_cancel(self):
        for rec in self:
            if rec.paid:
                raise exceptions.ValidationError(
                    _('Could not cancel this advance because'
                        ' the advance is already paid. '
                        'Please cancel the payment first.'))
            else:
                rec.move_id.unlink()
                rec.state = 'cancel'
                rec.message_post(_(
                    '<strong>Advance cancelled.</strong><ul>'
                    '<li><strong>Cancelled by: </strong>%s</li>'
                    '<li><strong>Cancelled at: </strong>%s</li>'
                    '</ul>') % (self.env.user.name, fields.Datetime.now()))

    @api.multi
    def action_cancel_draft(self):
        for rec in self:
            if rec.travel_id.state == 'cancel':
                raise exceptions.ValidationError(
                    _('Could not set this advance to draft because'
                        ' the travel is cancelled.'))
            else:
                rec.state = 'draft'
                rec.message_post(_(
                    '<strong>Advance drafted.</strong><ul>'
                    '<li><strong>Drafted by: </strong>%s</li>'
                    '<li><strong>Drafted at: </strong>%s</li>'
                    '</ul>') % (self.env.user.name, fields.Datetime.now()))
