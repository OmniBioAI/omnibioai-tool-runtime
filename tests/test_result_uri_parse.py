"""Parsing rules for RESULT_URI values across the s3://, azureblob://, and gs:// schemes.

Developer: Manish Kumar <manish@omnibioai.org>"""
# tests/test_result_uri_parse.py
from __future__ import annotations

import pytest

from omni_tool_runtime.result_uri import parse_result_uri


def test_parse_s3_uri_ok():
    """Split an s3:// URI into bucket and key path components."""
    p = parse_result_uri("s3://my-bucket/some/prefix/results.json")
    assert p.scheme == "s3"
    assert p.account_or_bucket == "my-bucket"
    assert p.container is None
    assert p.path == "some/prefix/results.json"


def test_parse_s3_uri_requires_bucket_and_key():
    """Reject s3:// URIs missing a bucket, or missing a key after the bucket."""
    with pytest.raises(ValueError):
        parse_result_uri("s3://")
    with pytest.raises(ValueError):
        parse_result_uri("s3://bucket-only")
    with pytest.raises(ValueError):
        parse_result_uri("s3://bucket/")


def test_parse_azureblob_uri_ok():
    """Split an azureblob:// URI into account, container, and blob path components."""
    p = parse_result_uri("azureblob://acct/container/path/to/results.json")
    assert p.scheme == "azureblob"
    assert p.account_or_bucket == "acct"
    assert p.container == "container"
    assert p.path == "path/to/results.json"


def test_parse_azureblob_uri_requires_container_and_path():
    """Reject azureblob:// URIs missing a container, or missing a path after the container."""
    with pytest.raises(ValueError):
        parse_result_uri("azureblob://acct/")
    with pytest.raises(ValueError):
        parse_result_uri("azureblob://acct/container")
    with pytest.raises(ValueError):
        parse_result_uri("azureblob://acct/container/")


def test_parse_gs_uri_ok():
    """Split a gs:// URI into bucket and key path components."""
    p = parse_result_uri("gs://my-bucket/some/prefix/results.json")
    assert p.scheme == "gs"
    assert p.account_or_bucket == "my-bucket"
    assert p.container is None
    assert p.path == "some/prefix/results.json"


def test_parse_gs_uri_requires_bucket_and_key():
    """Reject gs:// URIs missing a bucket, or missing a key after the bucket."""
    with pytest.raises(ValueError):
        parse_result_uri("gs://")
    with pytest.raises(ValueError):
        parse_result_uri("gs://bucket-only")
    with pytest.raises(ValueError):
        parse_result_uri("gs://bucket/")


def test_parse_rejects_unknown_scheme():
    """Reject a RESULT_URI scheme outside the supported s3/azureblob/gs set."""
    with pytest.raises(ValueError, match="Unsupported"):
        parse_result_uri("ftp://bucket/key")  # ftp is not supported


def test_parse_rejects_missing_scheme():
    """Reject a RESULT_URI with no scheme prefix at all."""
    with pytest.raises(ValueError, match="missing scheme"):
        parse_result_uri("bucket/key")
