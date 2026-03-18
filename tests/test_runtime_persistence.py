from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.orm import Session

from app.persistence.errors import PersistenceNotFoundError, PersistenceValidationError
from app.persistence.runtime_persistence import (
    PERSISTENCE_WARNING_INVALID_IDENTITY,
    PERSISTENCE_WARNING_INVALID_INPUT,
    PERSISTENCE_WARNING_MISSING_CONTEXT,
    PERSISTENCE_WARNING_NOT_FOUND,
    PERSISTENCE_WARNING_UNAVAILABLE,
    RuntimePersistenceService,
)
from app.schemas.agent import RunStatus


class _SessionStub:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _session_factory() -> _SessionStub:
    return _SessionStub()


def test_start_run_success_returns_internal_ids() -> None:
    thread_id = uuid4()
    run_id = uuid4()

    class _Repository:
        def __init__(self, _session: Session) -> None:
            pass

        def get_or_create_thread(self, **kwargs: object) -> object:
            return SimpleNamespace(id=kwargs["thread_id"])

        def create_run_started(self, **_kwargs: object) -> object:
            return SimpleNamespace(id=run_id)

    service = RuntimePersistenceService(
        session_factory=_session_factory,
        repository_factory=_Repository,
    )

    result = service.start_run(
        thread_id=thread_id,
        user_id=1,
        profile_id=2,
        profile_nick="nick",
    )

    assert result.thread_id == thread_id
    assert result.internal_run_id == run_id
    assert result.warnings == []


def test_start_run_invalid_identity_returns_warning() -> None:
    thread_id = uuid4()

    class _Repository:
        def __init__(self, _session: Session) -> None:
            pass

        def get_or_create_thread(self, **_kwargs: object) -> object:
            raise PersistenceValidationError("bad identity")

        def create_run_started(self, **_kwargs: object) -> object:
            raise AssertionError("must not be called")

    service = RuntimePersistenceService(
        session_factory=_session_factory,
        repository_factory=_Repository,
    )

    result = service.start_run(
        thread_id=thread_id,
        user_id="u-1",
        profile_id=2,
        profile_nick="nick",
    )

    assert result.warnings == [PERSISTENCE_WARNING_INVALID_IDENTITY]


def test_start_run_invalid_identity_is_detected_before_session_open() -> None:
    thread_id = uuid4()

    def _failing_session_factory() -> Session:
        raise AssertionError("session should not be opened for invalid identity")

    service = RuntimePersistenceService(
        session_factory=_failing_session_factory,
    )

    result = service.start_run(
        thread_id=thread_id,
        user_id="u-1",
        profile_id="p-1",
        profile_nick="nick",
    )

    assert result.warnings == [PERSISTENCE_WARNING_INVALID_IDENTITY]


def test_start_run_unavailable_returns_warning() -> None:
    thread_id = uuid4()

    class _Repository:
        def __init__(self, _session: Session) -> None:
            pass

        def get_or_create_thread(self, **_kwargs: object) -> object:
            raise RuntimeError("db down")

        def create_run_started(self, **_kwargs: object) -> object:
            raise AssertionError("must not be called")

    service = RuntimePersistenceService(
        session_factory=_session_factory,
        repository_factory=_Repository,
    )

    result = service.start_run(
        thread_id=thread_id,
        user_id=1,
        profile_id=2,
        profile_nick="nick",
    )

    assert result.warnings == [PERSISTENCE_WARNING_UNAVAILABLE]


def test_finish_run_success_updates_status_and_message() -> None:
    calls: list[str] = []

    class _Repository:
        def __init__(self, _session: Session) -> None:
            pass

        def update_run_terminal_status(self, **_kwargs: object) -> object:
            calls.append("update")
            return object()

        def write_message(self, **_kwargs: object) -> object:
            calls.append("message")
            return object()

    service = RuntimePersistenceService(
        session_factory=_session_factory,
        repository_factory=_Repository,
    )
    result = service.finish_run(
        thread_id=uuid4(),
        internal_run_id=uuid4(),
        status=RunStatus.COMPLETED,
        question="q",
        answer="a",
    )

    assert calls == ["update", "message"]
    assert result.warnings == []


def test_finish_run_missing_context_returns_warning() -> None:
    service = RuntimePersistenceService(session_factory=_session_factory)

    result = service.finish_run(
        thread_id=None,
        internal_run_id=None,
        status=RunStatus.FAILED,
        question="q",
        answer=None,
    )

    assert result.warnings == [PERSISTENCE_WARNING_MISSING_CONTEXT]


def test_finish_run_not_found_returns_warning() -> None:
    class _Repository:
        def __init__(self, _session: Session) -> None:
            pass

        def update_run_terminal_status(self, **_kwargs: object) -> object:
            raise PersistenceNotFoundError("missing run")

        def write_message(self, **_kwargs: object) -> object:
            raise AssertionError("must not be called")

    service = RuntimePersistenceService(
        session_factory=_session_factory,
        repository_factory=_Repository,
    )

    result = service.finish_run(
        thread_id=uuid4(),
        internal_run_id=uuid4(),
        status=RunStatus.DENIED,
        question="q",
        answer=None,
    )

    assert result.warnings == [PERSISTENCE_WARNING_NOT_FOUND]


def test_finish_run_invalid_input_returns_warning() -> None:
    class _Repository:
        def __init__(self, _session: Session) -> None:
            pass

        def update_run_terminal_status(self, **_kwargs: object) -> object:
            return object()

        def write_message(self, **_kwargs: object) -> object:
            raise PersistenceValidationError("bad question")

    service = RuntimePersistenceService(
        session_factory=_session_factory,
        repository_factory=_Repository,
    )

    result = service.finish_run(
        thread_id=uuid4(),
        internal_run_id=uuid4(),
        status=RunStatus.COMPLETED,
        question="",
        answer="a",
    )

    assert result.warnings == [PERSISTENCE_WARNING_INVALID_INPUT]


def test_finish_run_unavailable_returns_warning() -> None:
    class _Repository:
        def __init__(self, _session: Session) -> None:
            pass

        def update_run_terminal_status(self, **_kwargs: object) -> object:
            raise RuntimeError("db down")

        def write_message(self, **_kwargs: object) -> object:
            raise AssertionError("must not be called")

    service = RuntimePersistenceService(
        session_factory=_session_factory,
        repository_factory=_Repository,
    )

    result = service.finish_run(
        thread_id=uuid4(),
        internal_run_id=uuid4(),
        status=RunStatus.FAILED,
        question="q",
        answer=None,
    )

    assert result.warnings == [PERSISTENCE_WARNING_UNAVAILABLE]
