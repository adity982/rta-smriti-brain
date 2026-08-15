from unittest.mock import Mock

import pytest

from src.service import TaskService


def test_create_rejects_blank_titles() -> None:
    service = TaskService(Mock())

    with pytest.raises(ValueError, match="title is required"):
        service.create(1, "  ")


def test_create_persists_normalized_title() -> None:
    store = Mock()
    task = TaskService(store).create(1, "  Ship launch assets  ")

    assert task.title == "Ship launch assets"
    store.save.assert_called_once_with(task)
