def parse_cents(raw: str) -> int:
    normalized = raw.strip().replace("R$", "").replace(" ", "")
    if not normalized:
        raise ValueError("Empty money value.")

    sign = 1
    if normalized[0] in "+-":
        sign = -1 if normalized[0] == "-" else 1
        normalized = normalized[1:]

    if not normalized:
        raise ValueError("Empty money value.")

    if "," in normalized:
        whole, fraction = normalized.split(",", 1)
        if not whole or not fraction or not fraction.isdigit() or len(fraction) > 2:
            raise ValueError(f"Couldn't parse value `{raw}`.")
        if not whole.replace(".", "").isdigit():
            raise ValueError(f"Couldn't parse value `{raw}`.")

        whole_value = int(whole.replace(".", ""))
        cents = int(fraction.ljust(2, "0"))
        return sign * (whole_value * 100 + cents)

    if not normalized.replace(".", "").isdigit():
        raise ValueError(f"Couldn't parse value `{raw}`.")

    whole_value = int(normalized.replace(".", ""))
    return sign * whole_value * 100


def format_cents(value_cents: int) -> str:
    sign = "-" if value_cents < 0 else ""
    absolute = abs(value_cents)
    whole, fraction = divmod(absolute, 100)
    whole_str = f"{whole:,}".replace(",", ".")
    return f"R${sign}{whole_str},{fraction:02d}"