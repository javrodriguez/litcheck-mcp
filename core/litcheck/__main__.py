"""Run the command line with `python -m litcheck`."""
import sys

from .cli import main

if __name__ == '__main__':
    sys.exit(main())
