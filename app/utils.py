def calculate_upc_check_digit(upc11: str) -> str:
    digits = [int(d) for d in upc11]
    odd_sum = sum(digits[::2]) * 3
    even_sum = sum(digits[1::2])
    total = odd_sum + even_sum
    return str((10 - total % 10) % 10)

def generate_upc_from_id(item_id: int) -> str:
    base = str(item_id).zfill(11)
    return base + calculate_upc_check_digit(base)
