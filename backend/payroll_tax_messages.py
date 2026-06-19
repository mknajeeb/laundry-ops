"""Shared payroll tax disclaimer copy — internal estimates only, not filing software."""

# Tax withholding is entered manually in Payout Details; batch flow does not run the tax engine.
MANUAL_TAX_DEDUCTIONS_ONLY = True

MANUAL_DEDUCTIONS_NOTICE = (
    "Tax deductions are entered manually in Payout Details after the batch is approved."
)

ESTIMATE_DISCLAIMER = (
    "Estimated withholding — verify with accountant/payroll provider."
)

PAYROLL_ESTIMATE_PURPOSE = (
    "Internal payroll estimate and accountant review tool only. "
    "Not a certified payroll tax filing engine. "
    "Final withholding, filings, and payments must be verified by your accountant or payroll provider."
)

SEND_TO_ACCOUNTANT_W2_CONFIRM = (
    "Confirm this W-2 batch is ready for accountant review. "
    "Tax deductions will be entered manually in Payout Details."
)

ACCOUNTANT_BATCH_READY_MESSAGE = (
    "Payroll confirmed this W-2 batch is ready for your review. "
    "You may proceed with direct deposit forms and payroll processing."
)

ESTIMATED_WITHHOLDING_NOTICE = ESTIMATE_DISCLAIMER
