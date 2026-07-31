from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class ParsedTransaction:
    name: str
    value_cents: int
    method: str | None = None
    tags: list[str] = field(default_factory=list)
    desc: str | None = None

    @property
    def value(self) -> Decimal:
        """Returns monetary value as a Decimal (e.g., 123456 -> 1234.56)."""
        return Decimal(self.value_cents) / Decimal(100)


def parse_transaction_input(text: str) -> ParsedTransaction:
    if not text or ":" not in text:
        raise ValueError(
            "Invalid format. Input must contain a title followed by ':' (e.g. 'Mercado: 50,00')."
        )

    title_part, body_part = text.split(":", 1)

    name = title_part.strip()
    if not name:
        raise ValueError("Transaction title cannot be empty.")

    tokens = body_part.strip().split()
    if not tokens:
        raise ValueError("Missing transaction value after ':'")

    raw_value = tokens[0]
    try:
        clean_value = raw_value.replace(".", "").replace(",", ".")
        val_decimal = Decimal(clean_value)
        value_cents = round(val_decimal * 100)
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid monetary value: '{raw_value}'")

    method: str | None = None
    tags: list[str] = []
    desc_words: list[str] = []

    for token in tokens[1:]:
        if token.startswith("$") and len(token) > 1:
            method = token[1:].strip().lower()
        elif token.startswith("#") and len(token) > 1:
            tags.append(token[1:].strip().lower())
        else:
            desc_words.append(token)

    desc = " ".join(desc_words) if desc_words else None

    return ParsedTransaction(
        name=name,
        value_cents=value_cents,
        method=method,
        tags=tags,
        desc=desc,
    )
