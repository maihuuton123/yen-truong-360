from __future__ import annotations

from xml.sax.saxutils import escape


VERSION = 5
SIZE = VERSION * 4 + 17
DATA_CODEWORDS = 108
ECC_CODEWORDS = 26


def build_qr_svg(payload: str, *, scale: int = 8, border: int = 4) -> str:
    matrix = build_qr_matrix(payload)
    image_size = (SIZE + border * 2) * scale
    modules = []
    for y, row in enumerate(matrix):
        for x, value in enumerate(row):
            if value:
                modules.append(
                    f'<rect x="{(x + border) * scale}" y="{(y + border) * scale}" '
                    f'width="{scale}" height="{scale}"/>'
                )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{image_size}" height="{image_size}" '
        f'viewBox="0 0 {image_size} {image_size}" role="img" aria-label="QR Yen Truong 360">'
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        '<g fill="#14211a">'
        f'{"".join(modules)}'
        '</g>'
        f'<desc>{escape(payload)}</desc>'
        '</svg>'
    )


def build_qr_matrix(payload: str) -> list[list[bool]]:
    data = make_data_codewords(payload)
    ecc = reed_solomon_remainder(data, reed_solomon_generator(ECC_CODEWORDS))
    codewords = data + ecc
    bits = [(codeword >> bit) & 1 == 1 for codeword in codewords for bit in range(7, -1, -1)]

    modules: list[list[bool | None]] = [[None for _ in range(SIZE)] for _ in range(SIZE)]
    reserved = [[False for _ in range(SIZE)] for _ in range(SIZE)]
    draw_function_patterns(modules, reserved)
    draw_codewords(modules, reserved, bits)
    apply_mask_zero(modules, reserved)
    draw_format_bits(modules)

    return [[bool(value) for value in row] for row in modules]


def make_data_codewords(payload: str) -> list[int]:
    raw = payload.encode("utf-8")
    if len(raw) > 106:
        raise ValueError("QR payload is too long for the built-in version 5-L encoder.")

    bits = [0, 1, 0, 0]
    bits.extend((len(raw) >> bit) & 1 for bit in range(7, -1, -1))
    for byte in raw:
        bits.extend((byte >> bit) & 1 for bit in range(7, -1, -1))
    bits.extend([0] * min(4, DATA_CODEWORDS * 8 - len(bits)))
    while len(bits) % 8:
        bits.append(0)

    data = [bits[index] << 7 | bits[index + 1] << 6 | bits[index + 2] << 5 | bits[index + 3] << 4 |
            bits[index + 4] << 3 | bits[index + 5] << 2 | bits[index + 6] << 1 | bits[index + 7]
            for index in range(0, len(bits), 8)]
    pad = 0xEC
    while len(data) < DATA_CODEWORDS:
        data.append(pad)
        pad = 0x11 if pad == 0xEC else 0xEC
    return data


def draw_function_patterns(modules: list[list[bool | None]], reserved: list[list[bool]]) -> None:
    draw_finder(modules, reserved, 0, 0)
    draw_finder(modules, reserved, SIZE - 7, 0)
    draw_finder(modules, reserved, 0, SIZE - 7)
    draw_alignment(modules, reserved, 30, 30)

    for index in range(SIZE):
        if not reserved[6][index]:
            modules[6][index] = index % 2 == 0
            reserved[6][index] = True
        if not reserved[index][6]:
            modules[index][6] = index % 2 == 0
            reserved[index][6] = True

    modules[VERSION * 4 + 9][8] = True
    reserved[VERSION * 4 + 9][8] = True

    for index in range(9):
        reserve_format(reserved, 8, index)
        reserve_format(reserved, index, 8)
        reserve_format(reserved, SIZE - 1 - index, 8)
        reserve_format(reserved, 8, SIZE - 1 - index)


def draw_finder(modules: list[list[bool | None]], reserved: list[list[bool]], left: int, top: int) -> None:
    for dy in range(-1, 8):
        for dx in range(-1, 8):
            x = left + dx
            y = top + dy
            if not (0 <= x < SIZE and 0 <= y < SIZE):
                continue
            is_dark = 0 <= dx <= 6 and 0 <= dy <= 6 and (
                dx in {0, 6} or dy in {0, 6} or (2 <= dx <= 4 and 2 <= dy <= 4)
            )
            modules[y][x] = is_dark
            reserved[y][x] = True


def draw_alignment(modules: list[list[bool | None]], reserved: list[list[bool]], center_x: int, center_y: int) -> None:
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            x = center_x + dx
            y = center_y + dy
            modules[y][x] = max(abs(dx), abs(dy)) != 1
            reserved[y][x] = True


def reserve_format(reserved: list[list[bool]], x: int, y: int) -> None:
    if 0 <= x < SIZE and 0 <= y < SIZE:
        reserved[y][x] = True


def draw_codewords(modules: list[list[bool | None]], reserved: list[list[bool]], bits: list[bool]) -> None:
    bit_index = 0
    direction = -1
    x = SIZE - 1
    while x > 0:
        if x == 6:
            x -= 1
        for offset in range(SIZE):
            y = SIZE - 1 - offset if direction == -1 else offset
            for col in [x, x - 1]:
                if reserved[y][col]:
                    continue
                modules[y][col] = bits[bit_index] if bit_index < len(bits) else False
                bit_index += 1
        direction *= -1
        x -= 2


def apply_mask_zero(modules: list[list[bool | None]], reserved: list[list[bool]]) -> None:
    for y in range(SIZE):
        for x in range(SIZE):
            if not reserved[y][x] and (x + y) % 2 == 0:
                modules[y][x] = not modules[y][x]


def draw_format_bits(modules: list[list[bool | None]]) -> None:
    bits = format_bits(0b01, 0)
    for index in range(15):
        bit = (bits >> index) & 1 == 1
        if index < 6:
            modules[index][8] = bit
        elif index == 6:
            modules[7][8] = bit
        elif index == 7:
            modules[8][8] = bit
        elif index == 8:
            modules[8][7] = bit
        else:
            modules[8][14 - index] = bit

        if index < 8:
            modules[8][SIZE - 1 - index] = bit
        else:
            modules[SIZE - 15 + index][8] = bit


def format_bits(error_correction_bits: int, mask: int) -> int:
    data = (error_correction_bits << 3) | mask
    value = data << 10
    generator = 0x537
    for bit in range(14, 9, -1):
        if (value >> bit) & 1:
            value ^= generator << (bit - 10)
    return ((data << 10) | value) ^ 0x5412


def reed_solomon_generator(degree: int) -> list[int]:
    result = [1]
    root = 1
    for _ in range(degree):
        result = [gf_multiply(coefficient, root) for coefficient in result] + [0]
        for index in range(len(result) - 1):
            result[index + 1] ^= result[index]
        root = gf_multiply(root, 0x02)
    return result


def reed_solomon_remainder(data: list[int], generator: list[int]) -> list[int]:
    result = [0] * len(generator)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for index, coefficient in enumerate(generator):
            result[index] ^= gf_multiply(coefficient, factor)
    return result


def gf_multiply(x: int, y: int) -> int:
    product = 0
    for _ in range(8):
        if y & 1:
            product ^= x
        carry = x & 0x80
        x = (x << 1) & 0xFF
        if carry:
            x ^= 0x1D
        y >>= 1
    return product
