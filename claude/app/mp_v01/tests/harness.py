"""Zero-dependency test harness so QC needs nothing but Python."""
from __future__ import annotations
import traceback

_TESTS: list[tuple[str, callable]] = []
_RESULTS: list[tuple[str, bool, str]] = []


def test(fn):
    _TESTS.append((fn.__name__, fn))
    return fn


def assert_raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except exc:
        return True
    except Exception as e:
        raise AssertionError(f"expected {exc.__name__}, got {type(e).__name__}: {e}")
    raise AssertionError(f"expected {exc.__name__}, nothing raised")


def run_all(title: str) -> bool:
    print(f"\n{'='*72}\n{title}\n{'='*72}")
    passed = failed = 0
    for name, fn in _TESTS:
        try:
            fn()
            print(f"  PASS  {name}")
            _RESULTS.append((name, True, ""))
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}")
            print("        " + "\n        ".join(traceback.format_exc().splitlines()[-3:]))
            _RESULTS.append((name, False, str(e)))
            failed += 1
    print(f"\n  {passed} passed, {failed} failed")
    return failed == 0
