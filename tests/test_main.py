"""Tests for main.py CLI argument parsing and startup modes."""

import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from config import Settings
from main import parse_args


def test_parse_args_reindex():
    with patch.object(sys, "argv", ["main.py", "--reindex"]):
        args = parse_args()
        assert args.reindex is True
        assert args.no_reindex is False
        assert args.full_reindex is False


def test_parse_args_no_reindex():
    with patch.object(sys, "argv", ["main.py", "--no-reindex"]):
        args = parse_args()
        assert args.no_reindex is True
        assert args.reindex is False


def test_parse_args_full_reindex():
    with patch.object(sys, "argv", ["main.py", "--full-reindex"]):
        args = parse_args()
        assert args.full_reindex is True


def test_parse_args_requires_flag():
    with patch.object(sys, "argv", ["main.py"]):
        with pytest.raises(SystemExit):
            parse_args()


def test_parse_args_mutually_exclusive():
    with patch.object(sys, "argv", ["main.py", "--reindex", "--no-reindex"]):
        with pytest.raises(SystemExit):
            parse_args()
