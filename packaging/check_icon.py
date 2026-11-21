"""Check that built .exe files embed the Titanium icon at every size.

    pip install pefile
    python packaging/check_icon.py dist/Titanium.exe dist/TitaniumSetup.exe

Fails (exit 1) if an exe has no icon or is missing one of the sizes Windows
uses for Explorer, the taskbar, Start and the desktop.
"""
import struct
import sys

import pefile

WANTED = {16, 24, 32, 48, 64, 128, 256}
RT_GROUP_ICON = 14


def icon_sizes(path: str) -> set[int]:
    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]])
    if not hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        return set()
    for rtype in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if rtype.id != RT_GROUP_ICON:
            continue
        for entry in rtype.directory.entries:
            for lang in entry.directory.entries:
                data = pe.get_data(lang.data.struct.OffsetToData, lang.data.struct.Size)
                count = struct.unpack("<H", data[4:6])[0]
                return {data[6 + 14 * i] or 256 for i in range(count)}
    return set()


def main(paths: list[str]) -> int:
    bad = 0
    for p in paths:
        sizes = icon_sizes(p)
        missing = WANTED - sizes
        print(f"{p}: icon sizes {sorted(sizes) or 'NONE'}" + (f", missing {sorted(missing)}" if missing else ""))
        bad += bool(missing)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
