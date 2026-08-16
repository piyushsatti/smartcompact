"""Shared library for smartcompact's hooks. Standard library only.

Every function here returns a safe default instead of raising: these modules
run inside hook subprocesses, where a crash is worse than an abstention. A
later step's entry-point scripts import from these modules directly; nothing
in this package is meant to be run on its own.
"""
