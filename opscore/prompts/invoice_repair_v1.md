Your previous extraction of this invoice failed these checks:
{{ERRORS}}

Previous extraction:
{{PREVIOUS}}

Re-read the invoice text below and return a corrected extraction. Fix values you misread or mis-parsed. Do not change a value only to make a check pass: if the printed invoice itself does not add up, keep the printed values and lower field_confidence for the affected fields.

<invoice_text>
{{INVOICE_TEXT}}
</invoice_text>
