"""Small UPC-A SVG renderer for printable item labels."""

UPC_LEFT = ("0001101", "0011001", "0010011", "0111101", "0100011", "0110001", "0101111", "0111011", "0110111", "0001011")


def _invert(bits: str) -> str:
    return bits.translate(str.maketrans("01", "10"))


def upc_bars(upc: str) -> list[int]:
    """Return x positions for UPC-A bars."""
    bits = "101" + "".join(UPC_LEFT[int(digit)] for digit in upc[:6]) + "01010" + "".join(_invert(UPC_LEFT[int(digit)]) for digit in upc[6:]) + "101"
    return [index for index, bit in enumerate(bits) if bit == "1"]
