"""Run plain test_* functions as real cases, in addition to the legacy harness."""
from pathlib import Path
import importlib.util
import inspect
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))


def main() -> int:
    suite = unittest.TestSuite()
    for path in sorted(HERE.glob("test_*.py")):
        spec = importlib.util.spec_from_file_location("discovered_" + path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        for name, obj in sorted(vars(module).items()):
            if name.startswith("test_") and inspect.isfunction(obj) and obj.__module__ == module.__name__:
                suite.addTest(unittest.FunctionTestCase(obj, description=path.name + "::" + name))
    if not suite.countTestCases():
        raise RuntimeError("No additional tests discovered; do not report a false green")
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
