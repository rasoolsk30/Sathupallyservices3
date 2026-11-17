"""Behavioural probe for the mandatory guard behaviours (R2.4 + R2.5).

Runs against whatever `tests.guards` is importable, so it can be executed against both the
R2.3 (pre-fix) and R2.4 (fixed) module to prove the regression tests discriminate.

Usage:  PYTHONPATH=<backend dir> python3 probe_guard_behaviour.py
"""
import sys
from tests.guards import UnsafeTestDatabaseError, assert_disposable_test_database, verify_connected_database

GOOD = "postgresql+psycopg://u:p@127.0.0.1:5432/sathupally_test"
APP = "postgresql+psycopg://u:p@127.0.0.1:5432/sathupally"


def check(url, **kw):
    kw.setdefault("opt_in", "1")
    kw.setdefault("allow_remote", "")
    kw.setdefault("app_url", APP)
    assert_disposable_test_database(url, **kw)


class Fake:
    def __init__(self, db="sathupally_test", addr="127.0.0.1", port=5432, marker=None):
        self.db, self.addr, self.port, self.marker = db, addr, port, marker

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "current_database()" in sql:
            return type("R", (), {"one": lambda s: (self.db, self.addr, self.port)})()
        if "to_regclass" in sql:
            return type("R", (), {"scalar": lambda s: self.marker})()
        raise AssertionError(sql)


def refused(fn):
    try:
        fn()
        return False
    except UnsafeTestDatabaseError:
        return True
    except TypeError as exc:
        # Older builds cannot accept the app_url argument at all, which means the live
        # identity check is structurally unable to compare against the application database.
        print(f"       (not supported by this build: {exc})")
        return False


CASES = [
    ("1. localhost vs 127.0.0.1 cannot bypass collision",
     lambda: check(GOOD, app_url="postgresql+psycopg://u:p@localhost:5432/sathupally_test"), True),
    ("2. localhost vs ::1 cannot bypass collision",
     lambda: check("postgresql+psycopg://u:p@[::1]:5432/sathupally_test",
                   app_url="postgresql+psycopg://u:p@localhost:5432/sathupally_test"), True),
    ("3. 0.0.0.0 is rejected as a test host",
     lambda: check("postgresql+psycopg://u:p@0.0.0.0:5432/sathupally_test"), True),
    ("4. different port is allowed (different cluster)",
     lambda: check("postgresql+psycopg://u:p@127.0.0.1:5433/sathupally_test",
                   app_url="postgresql+psycopg://u:p@localhost:5432/sathupally_test"), False),
    ("5. different database name is allowed",
     lambda: check(GOOD, app_url="postgresql+psycopg://u:p@localhost:5432/sathupally"), False),
    ("6. valid test configuration still works",
     lambda: check(GOOD, app_url=APP), False),
    ("7. live reset blocked when identity is uncertain (alias hides app db)",
     lambda: verify_connected_database(Fake(), app_url="postgresql+psycopg://u:p@localhost:5432/sathupally_test"),
     True),
    # --- R2.5: the application-identity layer must fail CLOSED ---
    ("8. missing application DATABASE_URL refuses the reset",
     lambda: check(GOOD, app_url=""), True),
    ("9. unparseable application DATABASE_URL refuses the reset",
     lambda: check(GOOD, app_url="not-a-url"), True),
    ("10. application URL with no database name refuses the reset",
     lambda: check(GOOD, app_url="postgresql+psycopg://u:p@127.0.0.1:5432/"), True),
]

print(f"module under test: {sys.modules['tests.guards'].__file__}\n")
failures = 0
for label, fn, must_refuse in CASES:
    got_refused = refused(fn)
    ok = got_refused == must_refuse
    failures += 0 if ok else 1
    verdict = "PASS" if ok else "FAIL"
    outcome = "refused" if got_refused else "allowed"
    print(f"  [{verdict}] {label}  -> {outcome} (expected {'refused' if must_refuse else 'allowed'})")
print(f"\n{len(CASES) - failures}/{len(CASES)} behaviours correct")
sys.exit(0 if failures == 0 else 1)
