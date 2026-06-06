"""Allow `python -m eval` as a shortcut for `python -m eval.runner`."""
from eval.runner import main

if __name__ == "__main__":
    raise SystemExit(main())
