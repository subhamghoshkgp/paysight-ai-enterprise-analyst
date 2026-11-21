"""Export the source tables used by the demo as one reproducible CSV archive."""

import csv
import io
import os
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .data import DEFAULT, build, connect

ARCHIVE = DEFAULT.parent / "paysight-payments-v2.zip"


def export(snapshot=DEFAULT, destination=ARCHIVE):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
        staging = Path(tmp.name)
    try:
        with closing(connect(build(snapshot))) as db, ZipFile(staging, "w") as archive:
            for table in ("raw_transactions", "merchants", "banks"):
                rows = db.execute(f"SELECT * FROM {table} ORDER BY rowid")
                entry = ZipInfo(f"{table}.csv")
                entry.compress_type = ZIP_DEFLATED
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                with archive.open(entry, "w") as binary:
                    with io.TextIOWrapper(binary, encoding="utf-8", newline="") as stream:
                        writer = csv.writer(stream, lineterminator="\n")
                        writer.writerow([column[0] for column in rows.description])
                        writer.writerows(rows)
        os.replace(staging, destination)
    finally:
        staging.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    print(export())
