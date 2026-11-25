#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "snpsite.settings")
    if sys.argv[1:2] == ["test"]:  # test --parallel: each worker starts fresh (a fork of a process that runs DuckDB's
        import multiprocessing  # threads can hang its children), on Linux as on macOS and Windows

        multiprocessing.set_start_method("spawn")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
