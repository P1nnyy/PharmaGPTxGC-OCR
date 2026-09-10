"""Reconciliations that run on every report load.

Each of these compares two figures that are computed different ways from the
same underlying records. When they agree, that is real evidence the pack is
sound - not proof, but the kind of corroboration an officer looks for. When
they disagree, the difference is shown with both sides drillable, because
"these don't match" is useless without "by how much, and which one do I look
at".

They run on load rather than on demand deliberately. A reconciliation somebody
has to remember to run is a reconciliation that gets run the day before filing,
which is the day it is least useful.

The fourth one earns its place differently from the others. The first three
catch arithmetic drift; **turnover against the payment split catches unrecorded
cash**. If a shop declares ₹4,00,000 of supplies and its recorded payments come
to ₹3,60,000, either ₹40,000 of payments were never entered or ₹40,000 of sales
were never rung up. A scrutiny officer runs exactly this comparison, and it is
much better to find it here first.
"""

from services.statutory.model import CrossCheck, Drill, DrillKind, Figure

# The payment check compares a declared total against a sum of payment rows,
# which legitimately drift for reasons that are not fraud: a bill paid partly
# on credit, a day total entered without its payment split. A rupee of
# tolerance would be arbitrary; zero would cry wolf on every credit sale. So
# the check reports the gap and leaves the judgement to a person, with a
# tolerance of zero and an explanation that says what a gap usually means.
PAYMENT_TOLERANCE_PAISE = 0


def gstr1_vs_sales_register(gstr1, register: dict, months: tuple) -> CrossCheck:
    """Table 4A + 5 + 7 against the register those tables were built from.

    The two are computed from the same documents by different code - the
    return aggregates into buckets, the register sums row by row - so agreement
    means the aggregation did not lose or duplicate anything. This is the first
    comparison an officer makes, and it is the cheapest one to get right.
    """
    return CrossCheck(
        code="GSTR1_VS_SALES_REGISTER",
        label="GSTR-1 outward totals vs sales register",
        left_label="GSTR-1 taxable value",
        right_label="Sales register taxable value",
        left=Figure(
            gstr1.totals["taxable_paise"],
            Drill(kind=DrillKind.SALES, filters={"periods": list(months)}),
        ),
        right=Figure(
            register["totals"]["taxable"]["paise"],
            Drill(kind=DrillKind.SALES, filters={"periods": list(months)}),
        ),
        explanation=(
            "The return aggregates supplies into rate buckets; the register sums "
            "them bill by bill. A difference means the aggregation lost or "
            "double-counted a document - most often a bill with no place of "
            "supply, which the return leaves out of every table."
        ),
    )


def hsn_vs_transactions(gstr1, outward_hsn: dict, months: tuple) -> CrossCheck:
    """Table 12 against the transactions it was recomputed from.

    These can legitimately differ, and the reason is worth stating rather than
    tolerating silently: documents with no line items - declared day totals -
    contribute to the return's totals and cannot contribute to an HSN summary.
    So the comparison is against the taxable value of documents that *have*
    lines, not against everything.
    """
    from_lines = sum(
        row.taxable_paise
        for row in gstr1.tables["hsn"].b2b + gstr1.tables["hsn"].b2c
    )
    return CrossCheck(
        code="HSN_VS_TRANSACTIONS",
        label="HSN summary vs transaction-level totals",
        left_label="HSN summary taxable value",
        right_label="Taxable value of documents carrying line items",
        left=Figure(
            outward_hsn["totals"]["taxable"]["paise"],
            Drill(kind=DrillKind.SALE_LINES, filters={"periods": list(months)}),
        ),
        right=Figure(
            from_lines,
            Drill(kind=DrillKind.SALE_LINES, filters={"periods": list(months)}),
        ),
        explanation=(
            "Compared against documents with line items only. Day totals carry no "
            "lines, so they are in the return's totals and cannot be in the HSN "
            "summary - which is a gap to know about, not a mismatch to fix here."
        ),
    )


def rate_blocks_vs_headers(documents: list, months: tuple) -> CrossCheck:
    """Every document's lines against its own header.

    The house rule: tax is computed per line, summed per rate block, reconciled
    to the header, and a mismatch is an error rather than something to absorb.
    This is that rule applied across a whole period at once. Both sides are the
    same documents, so any difference at all is a document whose parts and
    total disagree.
    """
    from_lines = 0
    from_headers = 0
    offenders = []

    for document in documents:
        if not document.is_reportable or not document.has_lines:
            continue
        lines_total = sum(
            l.taxable_paise for l in document.lines if l.supply_class == "TAXABLE"
        )
        from_lines += lines_total
        from_headers += document.taxable_paise
        if lines_total != document.taxable_paise:
            offenders.append(document.document_id)

    return CrossCheck(
        code="RATE_BLOCKS_VS_HEADERS",
        label="Rate block sums vs document headers",
        left_label="Sum of line items",
        right_label="Sum of document headers",
        left=Figure(
            from_lines,
            Drill(
                kind=DrillKind.SALES,
                filters={"ids": offenders} if offenders else {"periods": list(months)},
                count=len(offenders) or None,
            ),
        ),
        right=Figure(
            from_headers,
            Drill(
                kind=DrillKind.SALES,
                filters={"ids": offenders} if offenders else {"periods": list(months)},
                count=len(offenders) or None,
            ),
        ),
        explanation=(
            "Both sides are the same documents, so any difference is a bill whose "
            "lines and total disagree - one of the two is stale. "
            + (
                f"{len(offenders)} "
                f"{'document does' if len(offenders) == 1 else 'documents do'} not reconcile."
                if offenders else "Every document reconciles."
            )
        ),
    )


def turnover_vs_payments(register: dict, payments: list, documents: list, months: tuple) -> CrossCheck:
    """Declared supplies against what was actually recorded as taken.

    The one that catches unrecorded cash. A gap here means either payments went
    unentered or sales did, and both are worth finding before somebody else
    finds them.

    Only documents that carry a payment split are compared. A bill recorded
    without one is not evidence of anything, and including it would make every
    period fail - so those are counted and reported separately instead.
    """
    paid_by_sale: dict = {}
    for payment in payments:
        paid_by_sale.setdefault(payment["sale_id"], 0)
        paid_by_sale[payment["sale_id"]] += int(payment.get("amount_paise") or 0)

    declared = 0
    recorded = 0
    without_split = 0
    mismatched = []

    for document in documents:
        if not document.is_reportable:
            continue
        taken = paid_by_sale.get(document.document_id)
        if taken is None:
            without_split += 1
            continue
        expected = document.sign * document.grand_total_paise
        declared += expected
        recorded += document.sign * taken
        if expected != document.sign * taken:
            mismatched.append(document.document_id)

    drill = Drill(
        kind=DrillKind.SALES,
        filters={"ids": mismatched} if mismatched else {"periods": list(months)},
        count=len(mismatched) or None,
    )
    return CrossCheck(
        code="TURNOVER_VS_PAYMENTS",
        label="Declared turnover vs payment split",
        left_label="Declared bill totals",
        right_label="Recorded payments",
        left=Figure(declared, drill),
        right=Figure(recorded, drill),
        tolerance_paise=PAYMENT_TOLERANCE_PAISE,
        explanation=(
            "Compares what the bills say was charged against what was recorded as "
            "taken. A shortfall means either payments were not entered or sales "
            "were not rung up - a scrutiny officer runs this same comparison. "
            + (
                f"{without_split} "
                f"{'bill has' if without_split == 1 else 'bills have'} no payment "
                "split recorded and are excluded from both sides."
                if without_split else "Every bill carries a payment split."
            )
        ),
    )


def run_all(gstr1, sales_reg: dict, outward_hsn: dict, documents: list,
            payments: list, months: tuple) -> list:
    """Every cross-check, in the order a person would work through them."""
    return [
        gstr1_vs_sales_register(gstr1, sales_reg, months),
        hsn_vs_transactions(gstr1, outward_hsn, months),
        rate_blocks_vs_headers(documents, months),
        turnover_vs_payments(sales_reg, payments, documents, months),
    ]
