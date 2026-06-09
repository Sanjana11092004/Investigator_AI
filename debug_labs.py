# debug_labs.py
import sys
sys.path.insert(0, ".")

from src.database.connection import get_db_context
from src.database.models.lab_result import LabResult

with get_db_context() as db:
    # Test 1: raw count of HIGH/LOW rows
    count = db.query(LabResult).filter(LabResult.lbnrind.in_(["HIGH", "LOW"])).count()
    print(f"Rows with lbnrind HIGH or LOW: {count}")

    # Test 2: fetch a few and print raw column values
    rows = db.query(LabResult).limit(3).all()
    for r in rows:
        print(f"\nusubjid   : {repr(r.usubjid)}")
        print(f"lbtest    : {repr(r.lbtest)}")
        print(f"lbtestcd  : {repr(r.lbtestcd)}")
        print(f"lbstresn  : {repr(r.lbstresn)}")
        print(f"lbstresu  : {repr(r.lbstresu)}")
        print(f"lbnrind   : {repr(r.lbnrind)}")
        print(f"lbnrlo    : {repr(r.lbnrlo)}")
        print(f"lbnrhi    : {repr(r.lbnrhi)}")
        print(f"lbclsig   : {repr(r.lbclsig)}")
        print(f"visit     : {repr(r.visit)}")
        print(f"lbdy      : {repr(r.lbdy)}")