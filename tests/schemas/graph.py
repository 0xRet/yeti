from core import database_arango

from fastapi.testclient import TestClient
import unittest
from core.schemas.observable import Observable
from core.schemas.entity import Malware
from core.schemas.graph import Relationship
import datetime
from core.web import webapp

client = TestClient(webapp.app)

class ObservableTest(unittest.TestCase):

    def setUp(self) -> None:
        database_arango.db.clear()
        self.observable1 = Observable(
            value="tomchop.me",
            type="hostname").save()
        self.observable2 = Observable(
            value="127.0.0.1",
            type="hostname").save()
        self.entity1 = Malware(name="plugx").save()

    def tearDown(self) -> None:
        database_arango.db.clear()

    def test_node_deletion_affects_link(self) -> None:
        """Tests that deleting a node also deletes assocaited relationships."""
        self.relationship = self.observable1.link_to(
            self.observable2, "resolves", "DNS resolution")
        all_relationships = list(Relationship.list())
        self.assertEqual(len(all_relationships), 1)

        self.observable1.delete()
        all_relationships = list(Relationship.list())
        self.assertEqual(len(all_relationships), 0)

    def test_observable_to_observable_link(self) -> None:
        """Tests that a link between two observables can be created."""
        self.relationship = self.observable1.link_to(
            self.observable2, "resolves", "DNS resolution")
        self.assertEqual(self.relationship.source, self.observable1.extended_id)
        self.assertEqual(self.relationship.target, self.observable2.extended_id)
        self.assertEqual(self.relationship.type, "resolves")
        self.assertEqual(self.relationship.description, "DNS resolution")

        neighbors = self.observable1.neighbors()
        self.assertEqual(len(neighbors.vertices), 1)
        self.assertEqual(
            neighbors.vertices[self.observable2.extended_id].value, "127.0.0.1")

    def test_observable_to_entity_link(self) -> None:
        """Tests that a link between an observable and an entity can be created."""
        self.relationship = self.observable1.link_to(
            self.entity1, "network-traffic", "Sends network traffic")
        self.assertEqual(self.relationship.source, self.observable1.extended_id)
        self.assertEqual(self.relationship.target, self.entity1.extended_id)
        self.assertEqual(self.relationship.type, "network-traffic")
        self.assertEqual(self.relationship.description, "Sends network traffic")

        neighbors = self.entity1.neighbors()
        self.assertEqual(len(neighbors.vertices), 1)
        self.assertEqual(
            neighbors.vertices[self.observable1.extended_id].value, "tomchop.me")

    def test_no_neighbors(self):
        """Tests that a node with no neighbors returns an empty list."""
        neighbors = self.observable1.neighbors()
        self.assertEqual(len(neighbors.vertices), 0)
