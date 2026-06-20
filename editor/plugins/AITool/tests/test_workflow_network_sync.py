import sys
import unittest
import builtins
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
AITOOL_ROOT = PROJECT_ROOT / "plugins" / "AITool"
if str(AITOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(AITOOL_ROOT))

from CoronaCore.core import network_sync_policy
from Quasar.ai_workflow import executor


class RecordingScope:
    def __init__(self, events, context):
        self.events = events
        self.context = context

    def __enter__(self):
        self.events.append(("enter", self.context.session_id, self.context.streaming))
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append(("exit", exc_type is not None))
        return False

    def commit(self):
        self.events.append(("commit", self.context.session_id))

    def preserve(self):
        self.events.append(("preserve", self.context.session_id))

    def rollback(self):
        self.events.append(("rollback", self.context.session_id))


class FakeActor:
    actor_type = "model"
    _geometry = object()
    _suppress_network_broadcast = False

    def __init__(self, name="chair", actor_guid="actor-chair"):
        self.name = name
        self.actor_guid = actor_guid
        self.parent = SimpleNamespace(
            route="Scene/main.scene",
            get_actors=lambda: [self],
        )

    def to_dict(self):
        return {
            "name": self.name,
            "actor_guid": self.actor_guid,
            "handle": 1234,
            "path": f"Resource/{self.name}.obj",
            "model": f"Resource/{self.name}.obj",
            "scene": self.parent.route,
        }


class FakeRegistry:
    def __init__(self, graph):
        self.graph = graph

    def get(self, _function_id):
        return self.graph

    def discover(self):
        return None


class WorkflowNetworkSyncTests(unittest.TestCase):
    def setUp(self):
        network_sync_policy.reset_for_tests()
        if hasattr(executor, "clear_workflow_execution_scope_factory"):
            executor.clear_workflow_execution_scope_factory()

    def tearDown(self):
        network_sync_policy.reset_for_tests()
        if hasattr(executor, "clear_workflow_execution_scope_factory"):
            executor.clear_workflow_execution_scope_factory()

    def _register_corona_sync_scope(self):
        executor.register_workflow_execution_scope_factory(
            lambda context: network_sync_policy.deferred_actor_broadcasts(
                pause_engine_sync=True,
                transaction_key=context.session_id,
            )
        )

    def test_quasar_executor_import_does_not_require_coronacore(self):
        original_import = builtins.__import__

        def block_coronacore(name, *args, **kwargs):
            if name.startswith("CoronaCore"):
                raise AssertionError(f"Quasar executor imported {name}")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("Quasar.ai_workflow.executor", None)
        with patch.object(builtins, "__import__", side_effect=block_coronacore):
            imported = importlib.import_module("Quasar.ai_workflow.executor")

        self.assertTrue(hasattr(imported, "run_workflow"))

    def test_run_workflow_uses_registered_scope_lifecycle(self):
        events = []

        class Graph:
            def invoke(self, state):
                return {**state, "output_parts": [{"content_type": "text"}]}

        executor.register_workflow_execution_scope_factory(
            lambda context: RecordingScope(events, context)
        )

        result = self._run_workflow_with_graph(Graph(), session_id="sid-hook")

        self.assertEqual(result, "ok")
        self.assertEqual(events, [
            ("enter", "sid-hook", False),
            ("commit", "sid-hook"),
            ("exit", False),
        ])

    def test_run_workflow_preserves_or_rolls_back_registered_scope(self):
        events = []

        class ReviewGraph:
            def invoke(self, state):
                return {**state, "awaiting_review": True}

        class ErrorGraph:
            def invoke(self, state):
                return {**state, "error": "failed"}

        executor.register_workflow_execution_scope_factory(
            lambda context: RecordingScope(events, context)
        )

        self._run_workflow_with_graph(ReviewGraph(), session_id="sid-review")
        self._run_workflow_with_graph(ErrorGraph(), session_id="sid-error")

        self.assertIn(("preserve", "sid-review"), events)
        self.assertIn(("rollback", "sid-error"), events)

    def test_run_workflow_without_registered_scope_does_not_defer_actor_create(self):
        events = []
        immediate_counts = []

        class Graph:
            def __init__(self):
                self.actor = FakeActor()

            def invoke(self, state):
                network_sync_policy.publish_actor_created(
                    self.actor,
                    prepare=None,
                    emit=lambda actor_data: events.append(actor_data),
                )
                immediate_counts.append(len(events))
                return {**state, "output_parts": [{"content_type": "text"}]}

        result = self._run_workflow_with_graph(Graph())

        self.assertEqual(result, "ok")
        self.assertEqual(immediate_counts, [1])
        self.assertEqual([event["name"] for event in events], ["chair"])

    def test_cabbage_adapter_registers_corona_workflow_sync_scope(self):
        from plugins.AITool.cai_extensions.register import (
            CabbageContext,
            CabbageWorkflowSyncPlugin,
        )

        runtime = SimpleNamespace(metadata={})
        context = CabbageContext(aitool_dir=Path("."), cai_dir=Path("."))

        with patch("Quasar.ai_workflow.register_workflow_execution_scope_factory") as register:
            result = CabbageWorkflowSyncPlugin(context).register(runtime)

        self.assertEqual(result["name"], "cabbage.workflow_sync")
        self.assertTrue(runtime.metadata["cabbage_adapter"]["cabbage.workflow_sync"])
        register.assert_called_once()

    def _run_workflow_with_graph(self, graph, *, session_id="sid-sync"):
        request = {"function_id": 21001, "session_id": session_id, "metadata": {}}
        with patch.object(executor, "get_workflow_registry", return_value=FakeRegistry(graph)), \
             patch.object(executor, "parse_request", return_value={
                 "function_id": 21001,
                 "session_id": session_id,
                 "metadata": {},
             }), \
             patch.object(executor, "format_response", return_value="ok"):
            return executor.run_workflow(21001, request)

    def _stream_workflow_with_graph(self, graph, *, session_id="sid-sync"):
        request = {"function_id": 21001, "session_id": session_id, "metadata": {}}
        with patch.object(executor, "get_workflow_registry", return_value=FakeRegistry(graph)), \
             patch.object(executor, "parse_request", return_value={
                 "function_id": 21001,
                 "session_id": session_id,
                 "metadata": {},
             }):
            return list(executor.stream_workflow(
                21001,
                request,
                checkpoint_nodes={"place"},
            ))

    def test_run_workflow_defers_actor_create_until_success(self):
        self._register_corona_sync_scope()
        events = []
        immediate_counts = []
        pause_calls = []

        class Graph:
            def __init__(self):
                self.actor = FakeActor()

            def invoke(self, state):
                network_sync_policy.publish_actor_created(
                    self.actor,
                    prepare=None,
                    emit=lambda actor_data: events.append(actor_data),
                )
                immediate_counts.append(len(events))
                return {**state, "output_parts": [{"content_type": "text"}]}

        with patch.object(network_sync_policy, "set_engine_sync_paused",
                          side_effect=lambda paused: pause_calls.append(paused)):
            result = self._run_workflow_with_graph(Graph())

        self.assertEqual(result, "ok")
        self.assertEqual(immediate_counts, [0])
        self.assertEqual([event["name"] for event in events], ["chair"])
        self.assertEqual(pause_calls, [True, False])

    def test_run_workflow_preserves_review_events_until_final_success(self):
        self._register_corona_sync_scope()
        events = []

        class ReviewGraph:
            def __init__(self):
                self.actor = FakeActor("sofa", "actor-sofa")

            def invoke(self, state):
                network_sync_policy.publish_actor_created(
                    self.actor,
                    prepare=None,
                    emit=lambda actor_data: events.append(actor_data),
                )
                return {**state, "awaiting_review": True}

        class FinalGraph:
            def invoke(self, state):
                return {**state, "output_parts": [{"content_type": "text"}]}

        review_graph = ReviewGraph()

        self._run_workflow_with_graph(review_graph)
        self.assertEqual(events, [])

        self._run_workflow_with_graph(FinalGraph())
        self.assertEqual([event["name"] for event in events], ["sofa"])

    def test_preserved_review_events_are_scoped_to_session(self):
        self._register_corona_sync_scope()
        events = []

        class ReviewGraph:
            def __init__(self):
                self.actor = FakeActor("sofa", "actor-sofa")

            def invoke(self, state):
                network_sync_policy.publish_actor_created(
                    self.actor,
                    prepare=None,
                    emit=lambda actor_data: events.append(actor_data),
                )
                return {**state, "awaiting_review": True}

        class FinalGraph:
            def invoke(self, state):
                return {**state, "output_parts": [{"content_type": "text"}]}

        review_graph = ReviewGraph()

        self._run_workflow_with_graph(review_graph, session_id="sid-review")
        self._run_workflow_with_graph(FinalGraph(), session_id="sid-other")
        self.assertEqual(events, [])

        self._run_workflow_with_graph(FinalGraph(), session_id="sid-review")
        self.assertEqual([event["name"] for event in events], ["sofa"])

    def test_stream_workflow_rolls_back_actor_create_when_update_has_error(self):
        self._register_corona_sync_scope()
        events = []

        class ErrorStreamGraph:
            def __init__(self):
                self.actor = FakeActor("bad_actor", "actor-bad")

            def stream(self, state, stream_mode=None):
                network_sync_policy.publish_actor_created(
                    self.actor,
                    prepare=None,
                    emit=lambda actor_data: events.append(actor_data),
                )
                yield {"place": {"error": "failed to place"}}

        self._stream_workflow_with_graph(ErrorStreamGraph())

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
