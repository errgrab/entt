from core.parsers import ParsedTransaction, parse_transaction_input
from core.services import TransactionService, WalletService


async def parse_finance(content: str) -> str:
    """Title: $type Amount #tag1 #tag2 Description"""
    parsed_tx: ParsedTransaction = parse_transaction_input(content)
    default_wallet = WalletService.get_selected()
    TransactionService.create(
        wallet=default_wallet,
        name=parsed_tx.name,
        value_cents=parsed_tx.value_cents,
        tx_type="outcome" if parsed_tx.value_cents < 0 else "income",
        method=parsed_tx.method,
        tags=parsed_tx.tags,
        desc=parsed_tx.desc,
    )
    total = default_wallet.sync_balance()

    return f"Total: {total}"


async def parse_note(content: str) -> str:
    raise NotImplementedError("This is not implemented yet.")


async def parse_task(content: str) -> str:
    raise NotImplementedError("This is not implemented yet.")


PARSERS = {
    "finance": parse_finance,
    "notes": parse_note,
    "tasks": parse_task,
}
