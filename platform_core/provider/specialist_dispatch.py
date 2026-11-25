"""Enter DeerFlow only when a validated request is about to reserve a model call."""

from functools import wraps

from . import task_usage


class _StartSpecialist(Exception):
    def __init__(self, name, task_id):
        self.name, self.task_id = name, task_id


def before_reservation(name, actor, request):
    from ..agents import deerflow_chat

    if not deerflow_chat.active():
        task = task_usage.current_task_id() or task_usage.identifier("specialist", name, actor, request)
        raise _StartSpecialist(name, task)


def hosted(operation):
    @wraps(operation)
    def perform(*args, **kwargs):
        from ..agents import deerflow_chat

        try:
            return operation(*args, **kwargs)
        except _StartSpecialist as start:
            name, task_id = start.name.replace(".", "-"), start.task_id
        # Release the preflight transaction and its traceback before waiting for the graph.
        # Recheck in the callback: a concurrent request could have finished meanwhile.
        with task_usage.scope("deerflow", task_id):
            try:
                return deerflow_chat.generate(lambda: operation(*args, **kwargs), name=name)
            except deerflow_chat.Unavailable as exc:
                raise ValueError(str(exc)) from exc

    return perform
