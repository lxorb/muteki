from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO


WIRE_TYPE_VARINT = 0
WIRE_TYPE_FIXED64 = 1
WIRE_TYPE_LENGTH_DELIMITED = 2
WIRE_TYPE_FIXED32 = 5


TEAM_NAMES = {
    0: "TEAM_A",
    1: "TEAM_B",
}

ENVIRONMENT_NAMES = {
    0: "ENV_EMPTY",
    1: "ENV_WALL",
    2: "ENV_ORE_TITANIUM",
    3: "ENV_ORE_AXIONITE",
}

SYMMETRY_NAMES = {
    0: "rotational",
    1: "horizontal",
    2: "vertical",
}


@dataclass(frozen=True)
class Pos:
    x: int
    y: int


@dataclass(frozen=True)
class CorePosition:
    id: int
    team: int
    position: Pos

    @property
    def team_name(self) -> str:
        return TEAM_NAMES.get(self.team, f"UNKNOWN_TEAM_{self.team}")


@dataclass(frozen=True)
class DecodedMap:
    width: int
    height: int
    rows: list[list[int]]
    cores: list[CorePosition]
    symmetry: int

    @property
    def symmetry_name(self) -> str:
        return SYMMETRY_NAMES.get(self.symmetry, f"unknown_{self.symmetry}")

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "rows": self.rows,
            "environment": [
                [
                    {
                        "value": value,
                        "name": ENVIRONMENT_NAMES.get(
                            value,
                            f"UNKNOWN_ENVIRONMENT_{value}",
                        ),
                    }
                    for value in row
                ]
                for row in self.rows
            ],
            "cores": [
                {
                    "id": core.id,
                    "team": core.team,
                    "team_name": core.team_name,
                    "position": asdict(core.position),
                }
                for core in self.cores
            ],
            "symmetry": self.symmetry,
            "symmetry_name": self.symmetry_name,
        }


class ProtobufDecodeError(ValueError):
    pass


class _Reader:
    def __init__(self, data: bytes):
        self._data = data
        self._index = 0

    def eof(self) -> bool:
        return self._index >= len(self._data)

    def read_byte(self) -> int:
        if self._index >= len(self._data):
            raise ProtobufDecodeError("Unexpected end of input")
        value = self._data[self._index]
        self._index += 1
        return value

    def read(self, size: int) -> bytes:
        end = self._index + size
        if end > len(self._data):
            raise ProtobufDecodeError("Unexpected end of input")
        chunk = self._data[self._index:end]
        self._index = end
        return chunk

    def read_varint(self) -> int:
        shift = 0
        value = 0
        while True:
            byte = self.read_byte()
            value |= (byte & 0x7F) << shift
            if (byte & 0x80) == 0:
                return value
            shift += 7
            if shift >= 64:
                raise ProtobufDecodeError("Varint is too long")

    def read_length_delimited(self) -> bytes:
        length = self.read_varint()
        return self.read(length)

    def skip_field(self, wire_type: int) -> None:
        if wire_type == WIRE_TYPE_VARINT:
            self.read_varint()
            return
        if wire_type == WIRE_TYPE_FIXED64:
            self.read(8)
            return
        if wire_type == WIRE_TYPE_LENGTH_DELIMITED:
            self.read_length_delimited()
            return
        if wire_type == WIRE_TYPE_FIXED32:
            self.read(4)
            return
        raise ProtobufDecodeError(f"Unsupported wire type {wire_type}")


def _decode_int32(value: int) -> int:
    value &= 0xFFFFFFFF
    if value >= 0x80000000:
        value -= 0x100000000
    return value


def _read_field_key(reader: _Reader) -> tuple[int, int]:
    key = reader.read_varint()
    if key == 0:
        raise ProtobufDecodeError("Invalid protobuf field key 0")
    return key >> 3, key & 0x07


def _parse_pos(data: bytes) -> Pos:
    reader = _Reader(data)
    x = 0
    y = 0
    while not reader.eof():
        field_number, wire_type = _read_field_key(reader)
        if field_number == 1 and wire_type == WIRE_TYPE_VARINT:
            x = _decode_int32(reader.read_varint())
        elif field_number == 2 and wire_type == WIRE_TYPE_VARINT:
            y = _decode_int32(reader.read_varint())
        else:
            reader.skip_field(wire_type)
    return Pos(x=x, y=y)


def _parse_core_position(data: bytes) -> CorePosition:
    reader = _Reader(data)
    core_id = 0
    team = 0
    position = Pos(0, 0)
    while not reader.eof():
        field_number, wire_type = _read_field_key(reader)
        if field_number == 1 and wire_type == WIRE_TYPE_VARINT:
            core_id = _decode_int32(reader.read_varint())
        elif field_number == 2 and wire_type == WIRE_TYPE_VARINT:
            team = _decode_int32(reader.read_varint())
        elif field_number == 3 and wire_type == WIRE_TYPE_LENGTH_DELIMITED:
            position = _parse_pos(reader.read_length_delimited())
        else:
            reader.skip_field(wire_type)
    return CorePosition(id=core_id, team=team, position=position)


def _parse_tile_row(data: bytes) -> list[int]:
    reader = _Reader(data)
    tiles: list[int] = []
    while not reader.eof():
        field_number, wire_type = _read_field_key(reader)
        if field_number != 1:
            reader.skip_field(wire_type)
            continue
        if wire_type == WIRE_TYPE_VARINT:
            tiles.append(_decode_int32(reader.read_varint()))
            continue
        if wire_type == WIRE_TYPE_LENGTH_DELIMITED:
            packed_reader = _Reader(reader.read_length_delimited())
            while not packed_reader.eof():
                tiles.append(_decode_int32(packed_reader.read_varint()))
            continue
        raise ProtobufDecodeError(
            f"Unsupported wire type {wire_type} for TileRow.tiles"
        )
    return tiles


def parse_map26_bytes(data: bytes) -> DecodedMap:
    reader = _Reader(data)
    width = 0
    height = 0
    rows: list[list[int]] = []
    cores: list[CorePosition] = []
    symmetry = 0

    while not reader.eof():
        field_number, wire_type = _read_field_key(reader)
        if field_number == 1 and wire_type == WIRE_TYPE_VARINT:
            width = _decode_int32(reader.read_varint())
        elif field_number == 2 and wire_type == WIRE_TYPE_VARINT:
            height = _decode_int32(reader.read_varint())
        elif field_number == 3 and wire_type == WIRE_TYPE_LENGTH_DELIMITED:
            rows.append(_parse_tile_row(reader.read_length_delimited()))
        elif field_number == 4 and wire_type == WIRE_TYPE_LENGTH_DELIMITED:
            cores.append(_parse_core_position(reader.read_length_delimited()))
        elif field_number == 5 and wire_type == WIRE_TYPE_VARINT:
            symmetry = _decode_int32(reader.read_varint())
        else:
            reader.skip_field(wire_type)

    return DecodedMap(
        width=width,
        height=height,
        rows=rows,
        cores=cores,
        symmetry=symmetry,
    )


def parse_map26_file(path: str | Path) -> DecodedMap:
    return parse_map26_bytes(Path(path).read_bytes())


def load_map26(stream: BinaryIO) -> DecodedMap:
    return parse_map26_bytes(stream.read())


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Decode a .map26 file")
    parser.add_argument("map_path", type=Path, help="Path to the .map26 file")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the decoded map JSON",
    )
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    decoded = parse_map26_file(args.map_path)
    indent = 2 if args.pretty else None
    print(json.dumps(decoded.to_dict(), indent=indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
