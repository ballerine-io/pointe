"""The command line."""

import argparse


def build_parser():
    parser = argparse.ArgumentParser(prog="almanac")
    parser.add_argument("--dry-run", action="store_true", help="print what would change")
    parser.add_argument("--dryrun", action="store_true", help="old spelling of --dry-run")
    parser.add_argument("--no-verify", action="store_true", help="skip the checksum check")
    parser.add_argument("--noverify", action="store_true", help="old spelling of --no-verify")
    parser.add_argument("--tz", default="UTC", help="time zone for printed times")
    parser.add_argument("--ts", default="iso", help="timestamp format")
    parser.add_argument("--json", action="store_true", help="one JSON document")
    parser.add_argument("--jsonl", action="store_true", help="one JSON object per line")
    return parser
