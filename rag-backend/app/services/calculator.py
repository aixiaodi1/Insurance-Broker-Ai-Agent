from decimal import Decimal, ROUND_HALF_UP
from typing import Any


def calc_reimbursement(
    expense: float | str | Decimal,
    deductible: float | str | Decimal,
    ratio: float | str | Decimal,
    limit: float | str | Decimal | None = None,
) -> dict[str, Any]:
    expense_d = Decimal(str(expense))
    deductible_d = Decimal(str(deductible))
    ratio_d = Decimal(str(ratio))

    payable_base = expense_d - deductible_d
    if payable_base < Decimal("0"):
        payable_base = Decimal("0")

    amount = payable_base * ratio_d
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if limit is not None:
        limit_d = Decimal(str(limit))
        amount = min(amount, limit_d)

    formula = f"({expense_d} - {deductible_d}) × {ratio_d}"
    result_str = str(amount)

    return {
        "formula": formula,
        "formula_expr": "(eligible_expense - deductible) * reimbursement_ratio",
        "inputs": {
            "eligible_expense": str(expense_d),
            "deductible": str(deductible_d),
            "reimbursement_ratio": str(ratio_d),
        },
        "result": result_str,
        "explanation": (
            f"可赔金额 = ({expense_d} - {deductible_d}) × {ratio_d} = {result_str} 元"
        ),
    }
