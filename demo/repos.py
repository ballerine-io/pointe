"""The two synthetic projects the demo sessions work on, and what the user says about them. Nothing here is real data."""

import subprocess
from pathlib import Path

BASE = Path("/tmp/demo")

CHECKOUT = {
    "payments.py": '''import random
import time


class ProviderError(Exception):
    pass


def charge(provider, order):
    """Charge an order. The provider rate-limits bursts of retries."""
    for attempt in range(5):
        try:
            return provider.charge(order.total_cents, order.card_token)
        except ProviderError:
            continue
    raise ProviderError("charge failed after 5 attempts")
''',
    "tax.py": '''def tax_for(order, tax_service):
    rate = tax_service.rate(order.region)
    return round(order.subtotal_cents * rate)
''',
    "run-tests.sh": '''#!/bin/sh
# The slow suite: talks to the provider sandbox.
echo "collecting 214 tests"
for suite in payments tax refunds webhooks; do
  sleep 9
  echo "  $suite ... ok"
done
echo "214 passed in 36.4s"
''',
    "README.md": "# checkout\n\nCharges orders through the payment provider.\n",
    ".gitignore": "__pycache__/\n",
}

BILLING = {
    "invoice.py": '''from decimal import Decimal


def total(lines):
    """Invoice total in dollars."""
    amount = sum(Decimal(str(line.qty)) * Decimal(str(line.unit_price)) for line in lines)
    return round(float(amount), 2)
''',
    "export.py": '''import csv
import json


def export(invoices, fmt, out):
    if fmt == "csv":
        writer = csv.writer(out)
        for inv in invoices:
            writer.writerow([inv.id, inv.customer, inv.total])
    elif fmt == "json":
        json.dump([inv.__dict__ for inv in invoices], out)
''',
    "README.md": "# billing\n\nInvoices and exports.\n",
    ".gitignore": "__pycache__/\n",
}

CHECKOUT_TASK = ("charge() in payments.py retries five times with no delay. Change it to exponential backoff with jitter, at "
                 "most 3 attempts. Not a fixed delay: the provider rate-limits bursts, and fixed delays make every client "
                 "retry at the same moment. Edit the file only, then say done in one line.")
BILLING_TASK = ("total() in invoice.py rounds through float, so 2.675 becomes 2.67. Make it round half-up to cents with "
                "Decimal and return a Decimal. Edit, then commit with the message 'Round invoice totals half-up'. "
                "Then say done in one line.")

THOUGHTS = [
    "So for the invoice export, I'm not sure we need the CSV path at all.",
    "Finance only ever opens the PDF,",
    "and the CSV breaks every time someone adds a column.",
    "Maybe we keep JSON for the API, and drop CSV next release.",
]


def _git(cwd: Path, command: str) -> None:
    subprocess.run(command, shell=True, cwd=cwd, check=True, capture_output=True)


def _repo(name: str, files: dict) -> Path:
    path = BASE / name
    subprocess.run(["rm", "-rf", str(path), str(BASE / f"{name}.git")], check=True)
    path.mkdir(parents=True)
    for file, body in files.items():
        (path / file).write_text(body)
    (path / "run-tests.sh").chmod(0o755) if (path / "run-tests.sh").exists() else None
    _git(path, "git init -q -b main && git add -A && git -c user.email=dev@example.com -c user.name=dev commit -qm init")
    _git(BASE, f"git init -q --bare {name}.git")
    _git(path, f"git remote add origin {BASE / name}.git && git push -q origin main")
    return path


def make() -> tuple[Path, Path]:
    checkout = _repo("checkout", CHECKOUT)
    for package in ("", "tests", "vendor/sdk"):  # what "delete every pycache folder" finds
        cache = checkout / package / "__pycache__"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "payments.cpython-313.pyc").write_bytes(b"\0" * 64)
    billing = _repo("billing", BILLING)
    for path in (checkout, billing):
        _git(path, "git config user.email dev@example.com && git config user.name dev")
    return checkout, billing
