"""Checksums of published pages."""

import hashlib


def checksum_sha224(data):
    return hashlib.sha224(data).hexdigest()


def checksum_sha256(data):
    return hashlib.sha256(data).hexdigest()


def checksum_sha512(data):
    return hashlib.sha512(data).hexdigest()
